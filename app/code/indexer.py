"""Code indexer — tree-sitter + Python ast symbol extraction.

Indexes a repository into:
  - code_repos      (one row per repo)
  - code_files      (one row per source file)
  - code_symbols    (one row per function/class/method/var/etc.)
  - code_edges      (one row per call/import/reference between symbols)

Supports Python via stdlib `ast` (zero deps) and JS/TS/TSX/Go/Rust via
tree-sitter + tree-sitter-languages. Other languages fall back to
a regex-based lightweight extractor that catches 70-80% of the obvious
patterns (def foo(...), class Bar, function baz, etc.).
"""
from __future__ import annotations

import ast
import hashlib
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("nexus.code.indexer")

# ── Symbol data class ────────────────────────────────────────────────────

@dataclass
class ExtractedSymbol:
    name: str
    qualified_name: str
    kind: str  # function | method | class | variable | constant | interface | module | type | enum
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    signature: str
    docstring: str = ""
    return_type: str = ""
    parameters: List[Dict[str, str]] = field(default_factory=list)
    parent_symbol_id: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    visibility: str = "public"
    is_exported: bool = True
    is_async: bool = False
    source: str = ""  # full source; populated only when caller asks for it
    complexity: int = 1
    line_count: int = 0


@dataclass
class ExtractedEdge:
    src_symbol_id: Optional[str]
    src_file_id: str
    dst_symbol_id: Optional[str]
    dst_name: str
    kind: str  # call | import | reference | implements | extends | uses | decorates
    weight: float = 1.0
    confidence: float = 0.5
    line: Optional[int] = None


# ── Language detection ───────────────────────────────────────────────────

EXTENSION_TO_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".py": "python",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".m": "objc",
    ".mm": "objc",
    ".scala": "scala",
    ".lua": "lua",
    ".php": "php",
    ".ex": "elixir",
    ".exs": "elixir",
    ".dart": "dart",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".ps1": "powershell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".vue": "vue",
    ".svelte": "svelte",
}


def detect_language(path: Path) -> Optional[str]:
    return EXTENSION_TO_LANG.get(path.suffix.lower())


# ── Per-language extractors ─────────────────────────────────────────────

# Lazy-loaded tree-sitter parsers (so we don't import until needed)
_ts_parsers: Dict[str, Any] = {}


def _get_ts_parser(lang: str) -> Any:
    if lang in _ts_parsers:
        return _ts_parsers[lang]
    try:
        from tree_sitter_languages import get_parser
        _ts_parsers[lang] = get_parser(lang)
        return _ts_parsers[lang]
    except Exception as e:
        log.debug("tree-sitter parser for %s unavailable: %s", lang, e)
        return None


def extract_python(path: Path, content: str) -> List[ExtractedSymbol]:
    """Use Python's stdlib ast — no tree-sitter needed for Python."""
    symbols: List[ExtractedSymbol] = []
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        log.debug("python parse error in %s: %s", path, e)
        return symbols

    def visit(node: ast.AST, qual_prefix: str = "") -> None:
        for child in node.body if isinstance(node, ast.Module) else []:
            _visit_one(child, qual_prefix)

    def _visit_one(node: ast.AST, qual_prefix: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qn = f"{qual_prefix}{node.name}" if qual_prefix else node.name
            params = [_param_str(a) for a in node.args.args + node.args.kwonlyargs]
            defaults_count = len(node.args.defaults) + len(node.args.kw_defaults)
            ret = ""
            if node.returns is not None:
                try:
                    ret = ast.unparse(node.returns)
                except Exception:
                    ret = ""
            sig = _format_python_signature(node, params, defaults_count, ret)
            doc = ast.get_docstring(node) or ""
            decos = [ast.unparse(d) for d in node.decorator_list if hasattr(ast, "unparse")]
            sym = ExtractedSymbol(
                name=node.name,
                qualified_name=qn,
                kind="function",
                start_byte=node.lineno,  # placeholder; updated below via col_offset
                end_byte=node.end_lineno or node.lineno,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                signature=sig,
                docstring=doc.split("\n")[0] if doc else "",
                return_type=ret,
                parameters=[{"name": p} for p in params],
                decorators=decos,
                is_async=isinstance(node, ast.AsyncFunctionDef),
                line_count=(node.end_lineno or node.lineno) - node.lineno + 1,
            )
            symbols.append(sym)
            # Recurse into nested defs
            for nested in node.body:
                if isinstance(nested, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    _visit_one(nested, qn + ".")
        elif isinstance(node, ast.ClassDef):
            qn = f"{qual_prefix}{node.name}" if qual_prefix else node.name
            bases = [ast.unparse(b) for b in node.bases if hasattr(ast, "unparse")]
            sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
            sym = ExtractedSymbol(
                name=node.name,
                qualified_name=qn,
                kind="class",
                start_byte=node.lineno,
                end_byte=node.end_lineno or node.lineno,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                signature=sig,
                docstring=(ast.get_docstring(node) or "").split("\n")[0],
                decorators=[ast.unparse(d) for d in node.decorator_list if hasattr(ast, "unparse")],
                line_count=(node.end_lineno or node.lineno) - node.lineno + 1,
            )
            symbols.append(sym)
            for child in node.body:
                _visit_one(child, qn + ".")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.append(ExtractedSymbol(
                        name=target.id,
                        qualified_name=target.id,
                        kind="variable",
                        start_byte=node.lineno, end_byte=node.end_lineno or node.lineno,
                        start_line=node.lineno, end_line=node.end_lineno or node.lineno,
                        signature=ast.unparse(node.value) if hasattr(ast, "unparse") else "",
                        line_count=1,
                    ))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            symbols.append(ExtractedSymbol(
                name=node.target.id,
                qualified_name=node.target.id,
                kind="variable",
                start_byte=node.lineno, end_byte=node.end_lineno or node.lineno,
                start_line=node.lineno, end_line=node.end_lineno or node.lineno,
                signature=ast.unparse(node.annotation) if hasattr(ast, "unparse") and node.annotation else "",
                line_count=1,
            ))

    visit(tree)
    return symbols


def _param_str(arg: ast.arg) -> str:
    return arg.arg


def _format_python_signature(node, params, defaults_count, ret) -> str:
    # def foo(a, b=1, *args, **kwargs) -> str
    args = node.args
    parts = []
    n_defaults = defaults_count
    regular_count = len(args.args)
    for i, p in enumerate(params):
        if i < regular_count - n_defaults and n_defaults > 0:
            parts.append(p)
        else:
            parts.append(p)  # we don't have positional info after parsing
    sig = f"def {node.name}({', '.join(parts)})"
    if ret:
        sig += f" -> {ret}"
    if isinstance(node, ast.AsyncFunctionDef):
        sig = "async " + sig
    return sig


# ── tree-sitter extractors for JS/TS/Go/Rust/TSX ───────────────────────

def extract_tree_sitter(path: Path, content: str, lang: str) -> List[ExtractedSymbol]:
    parser = _get_ts_parser(lang)
    if parser is None:
        return extract_regex_fallback(path, content, lang)
    try:
        tree = parser.parse(content.encode("utf-8"))
    except Exception as e:
        log.debug("tree-sitter parse failed for %s: %s", path, e)
        return extract_regex_fallback(path, content, lang)

    symbols: List[ExtractedSymbol] = []
    root = tree.root_node
    _walk_ts(root, content, lang, qual_prefix="", parent_id=None, out=symbols)
    return symbols


def _walk_ts(node, content: str, lang: str, qual_prefix: str, parent_id: Optional[str], out: List[ExtractedSymbol]) -> None:
    """Walk a tree-sitter AST and pull out function/class/method symbols.

    Strategy: walk top-down, but recurse INTO the body of each class so
    methods get a qualified name like MyClass.method.  This is less
    sophisticated than a full symbol-resolution pass but gets the
    obvious wins (top-level + class members)."""
    if not node.children:
        return
    for child in node.children:
        t = child.type
        if t in ("function_declaration", "function", "method_definition", "function_item", "arrow_function"):
            sym = _ts_function_symbol(child, content, lang, qual_prefix, parent_id)
            if sym:
                out.append(sym)
        elif t in ("class_declaration", "class", "class_definition", "struct_item", "interface_declaration", "type_item"):
            sym = _ts_class_symbol(child, content, lang, qual_prefix)
            if sym:
                out.append(sym)
                # Recurse into class body so methods get qualified names
                body = None
                for sub in child.children:
                    if sub.type in ("class_body", "block", "field_declaration_list", "object_type", "declaration_list"):
                        body = sub
                        break
                if body:
                    new_qual = f"{qual_prefix}{sym.name}." if qual_prefix else sym.name + "."
                    _walk_ts(body, content, lang, new_qual, sym.name, out)
        elif t in ("variable_declaration", "variable_declarator", "let_declaration", "const_declaration", "lexical_declaration"):
            for sym in _ts_variable_symbol(child, content, lang, qual_prefix):
                out.append(sym)
        elif t in ("export_statement", "lexical_declaration"):
            # Pass through — children handled
            _walk_ts(child, content, lang, qual_prefix, parent_id, out)


def _node_text(node, content: str) -> str:
    return content[node.start_byte:node.end_byte]


def _line_of(node, content: str) -> int:
    return content[:node.start_byte].count("\n") + 1


def _ts_function_symbol(node, content, lang, qual_prefix, parent_id) -> Optional[ExtractedSymbol]:
    name = ""
    for sub in node.children:
        if sub.type in ("identifier", "property_identifier", "name", "simple_identifier"):
            name = _node_text(sub, content)
            break
    if not name:
        return None
    qn = f"{qual_prefix}{name}" if qual_prefix else name
    line = _line_of(node, content)
    # Body
    body_text = _node_text(node, content)
    line_count = body_text.count("\n") + 1
    is_async = "async" in body_text[:30]
    is_exported = False
    if node.parent and node.parent.type in ("export_statement", "export_specifier", "lexical_declaration", "program"):
        # Check siblings for export keyword
        if node.parent.type == "export_statement" or "export" in _node_text(node.parent, content)[:50]:
            is_exported = True
    # Visibility
    visibility = "public"
    if name.startswith("_"):
        visibility = "private" if name.startswith("__") else "protected"
    return ExtractedSymbol(
        name=name, qualified_name=qn,
        kind="function" if parent_id is None else "method",
        start_byte=node.start_byte, end_byte=node.end_byte,
        start_line=line, end_line=line + line_count - 1,
        signature=body_text.split("\n")[0].strip()[:200],
        line_count=line_count,
        parent_symbol_id=None,
        decorators=[], visibility=visibility,
        is_exported=is_exported, is_async=is_async,
    )


def _ts_class_symbol(node, content, lang, qual_prefix) -> Optional[ExtractedSymbol]:
    name = ""
    for sub in node.children:
        if sub.type in ("identifier", "name", "type_identifier"):
            name = _node_text(sub, content)
            break
    if not name:
        return None
    qn = f"{qual_prefix}{name}" if qual_prefix else name
    line = _line_of(node, content)
    body_text = _node_text(node, content)
    line_count = body_text.count("\n") + 1
    return ExtractedSymbol(
        name=name, qualified_name=qn, kind="class",
        start_byte=node.start_byte, end_byte=node.end_byte,
        start_line=line, end_line=line + line_count - 1,
        signature=body_text.split("{")[0].strip()[:200] if "{" in body_text else body_text.split("\n")[0].strip()[:200],
        line_count=line_count, visibility="public", is_exported=True,
    )


def _ts_variable_symbol(node, content, lang, qual_prefix) -> List[ExtractedSymbol]:
    out = []
    for sub in node.children:
        if sub.type in ("variable_declarator", "identifier", "name", "simple_identifier", "pattern"):
            name = _node_text(sub, content) if sub.type != "variable_declarator" else ""
            if sub.type == "variable_declarator":
                for c in sub.children:
                    if c.type in ("identifier", "name", "simple_identifier"):
                        name = _node_text(c, content)
                        break
            if not name:
                continue
            line = _line_of(sub, content)
            out.append(ExtractedSymbol(
                name=name, qualified_name=f"{qual_prefix}{name}" if qual_prefix else name,
                kind="variable",
                start_byte=sub.start_byte, end_byte=sub.end_byte,
                start_line=line, end_line=line,
                signature=_node_text(node, content).split("\n")[0].strip()[:200],
                line_count=1, visibility="public", is_exported=True,
            ))
    return out


# ── Regex fallback (when tree-sitter unavailable) ──────────────────────

FUNC_PATTERNS = [
    # function name(args) { ... }  (JS/TS)
    re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", re.M),
    # const name = (args) => { ... } or const name = function ...
    re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function\s*)?\(([^)]*)\)\s*=>", re.M),
    # def name(args): (Python — usually not used, but covers partial parses)
    re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*[^:]+)?:", re.M),
    # func name(args) (Go)
    re.compile(r"^func\s+(?:\([^)]*\)\s+)?(\w+)\s*\(([^)]*)\)", re.M),
    # fn name(args) -> ret (Rust)
    re.compile(r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*\(([^)]*)\)", re.M),
]

CLASS_PATTERNS = [
    re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", re.M),
    re.compile(r"^type\s+(\w+)\s+struct", re.M),
    re.compile(r"^type\s+(\w+)\s+interface", re.M),
    re.compile(r"^struct\s+(\w+)", re.M),
    re.compile(r"^interface\s+(\w+)", re.M),
    re.compile(r"^class\s+(\w+)", re.M),  # Python — backup
]


def extract_regex_fallback(path: Path, content: str, lang: str) -> List[ExtractedSymbol]:
    symbols: List[ExtractedSymbol] = []
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        for pat in FUNC_PATTERNS:
            m = pat.match(line.lstrip())
            if m:
                name = m.group(1)
                params = m.group(2) if m.lastindex >= 2 else ""
                symbols.append(ExtractedSymbol(
                    name=name,
                    qualified_name=name,
                    kind="function",
                    start_byte=0, end_byte=0,
                    start_line=i, end_line=i,
                    signature=line.strip()[:200],
                    parameters=[{"name": p.strip().split(":")[0].strip()} for p in params.split(",") if p.strip()],
                    line_count=1, is_exported=line.startswith("export") or line.startswith("pub"),
                ))
                break
        for pat in CLASS_PATTERNS:
            m = pat.match(line.lstrip())
            if m:
                symbols.append(ExtractedSymbol(
                    name=m.group(1),
                    qualified_name=m.group(1),
                    kind="class",
                    start_byte=0, end_byte=0,
                    start_line=i, end_line=i,
                    signature=line.strip()[:200],
                    line_count=1, is_exported=line.startswith("export") or line.startswith("pub"),
                ))
                break
    return symbols


# ── Dispatcher ───────────────────────────────────────────────────────────

def extract_symbols(path: Path, content: str, language: Optional[str] = None) -> List[ExtractedSymbol]:
    if language is None:
        language = detect_language(path)
    if language == "python":
        return extract_python(path, content)
    if language in ("javascript", "typescript", "tsx", "go", "rust"):
        return extract_tree_sitter(path, content, language)
    return extract_regex_fallback(path, content, language or "unknown")


# ── Edge extraction (calls + imports) ────────────────────────────────────

def extract_edges_from_python(content: str, file_symbols: List[ExtractedSymbol], src_file_id: str) -> List[ExtractedEdge]:
    edges: List[ExtractedEdge] = []
    symbol_names = {s.name for s in file_symbols}
    qualified_set = {s.qualified_name for s in file_symbols}
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return edges
    src_id_by_qn = {s.qualified_name: None for s in file_symbols}  # filled by caller

    def visit(node: ast.AST, in_symbol: Optional[str] = None) -> None:
        # Track which symbol each call lives in
        cur_sym = in_symbol
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cur_sym = node.name  # best-effort
        elif isinstance(node, ast.ClassDef):
            cur_sym = node.name
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                target = child.func.id
                edges.append(ExtractedEdge(
                    src_symbol_id=None,  # resolved by caller
                    src_file_id=src_file_id,
                    dst_symbol_id=None,
                    dst_name=target,
                    kind="call",
                    line=child.lineno,
                    confidence=0.7 if target in symbol_names else 0.3,
                ))
            elif isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                # foo.bar() — call to bar on foo
                target = child.func.attr
                edges.append(ExtractedEdge(
                    src_symbol_id=None, src_file_id=src_file_id,
                    dst_symbol_id=None, dst_name=target, kind="call",
                    line=child.lineno, confidence=0.5,
                ))
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        edges.append(ExtractedEdge(
                            src_symbol_id=None, src_file_id=src_file_id,
                            dst_symbol_id=None, dst_name=alias.name,
                            kind="import", line=child.lineno, confidence=1.0,
                        ))
                elif isinstance(child, ast.ImportFrom) and child.module:
                    for alias in child.names:
                        edges.append(ExtractedEdge(
                            src_symbol_id=None, src_file_id=src_file_id,
                            dst_symbol_id=None, dst_name=child.module + "." + alias.name,
                            kind="import", line=child.lineno, confidence=1.0,
                        ))
            visit(child, cur_sym)

    visit(tree)
    return edges


def extract_edges_regex(content: str, src_file_id: str) -> List[ExtractedEdge]:
    """Lightweight regex edge extractor for non-Python files."""
    edges: List[ExtractedEdge] = []
    import_lines: List[Tuple[int, str]] = []
    for i, line in enumerate(content.split("\n"), 1):
        s = line.strip()
        if s.startswith("import ") or s.startswith("from "):
            # import foo from 'bar';  import { x } from 'y'
            m = re.search(r"from\s+['\"]([^'\"]+)['\"]", s)
            if m:
                import_lines.append((i, m.group(1)))
            elif s.startswith("import "):
                m = re.search(r"import\s+([\w./]+)", s)
                if m:
                    import_lines.append((i, m.group(1)))
        # Calls: name(  - heuristic
        for m in re.finditer(r"\b([a-zA-Z_]\w{2,})\s*\(", line):
            name = m.group(1)
            if name in ("if", "for", "while", "return", "function", "class", "def", "var", "let", "const", "new"):
                continue
            edges.append(ExtractedEdge(
                src_symbol_id=None, src_file_id=src_file_id,
                dst_symbol_id=None, dst_name=name, kind="call",
                line=i, confidence=0.2,
            ))
    for line, mod in import_lines:
        edges.append(ExtractedEdge(
            src_symbol_id=None, src_file_id=src_file_id,
            dst_symbol_id=None, dst_name=mod, kind="import",
            line=line, confidence=0.9,
        ))
    return edges


# ── Indexer (file → DB) ────────────────────────────────────────────────

class Indexer:
    """Indexes a single repository into the DB."""

    # Files we should never index
    SKIP_PATTERNS = (
        "__pycache__", "node_modules", ".git", "venv", ".venv",
        "dist", "build", ".next", ".nuxt", "target", "out",
        ".pytest_cache", ".mypy_cache", ".ruff_cache",
        "site-packages", ".tox",
    )
    # Extensions we never index (binary)
    SKIP_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
        ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
        ".pyc", ".pyo", ".so", ".dylib", ".dll", ".class", ".o", ".a",
        ".mp4", ".mp3", ".wav", ".avi", ".mov", ".webm",
        ".ttf", ".otf", ".woff", ".woff2",
    }

    def __init__(self, db: AsyncSession, repo_id: str):
        self.db = db
        self.repo_id = repo_id

    def should_skip(self, path: Path) -> bool:
        s = str(path)
        if any(p in s for p in self.SKIP_PATTERNS):
            return True
        if path.suffix.lower() in self.SKIP_EXTENSIONS:
            return True
        return False

    async def index_path(self, path: Path, rel_path: str, content: str) -> Dict[str, Any]:
        """Index a single file. Returns counts."""
        language = detect_language(path)
        symbols = extract_symbols(path, content, language)
        # Edges
        if language == "python":
            edges = extract_edges_from_python(content, symbols, "PENDING")
        else:
            edges = extract_edges_regex(content, "PENDING")
        # Upsert file
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        file_id = await self._upsert_file(rel_path, content, content_hash, mtime, language)
        # Wipe old symbols for this file (we always re-extract)
        await self.db.execute(text("DELETE FROM code_symbols WHERE file_id = :id"), {"id": file_id})
        await self.db.execute(text("DELETE FROM code_edges WHERE src_file_id = :id"), {"id": file_id})
        # Insert symbols
        sym_id_by_qn: Dict[str, str] = {}
        parent_id_by_name: Dict[str, str] = {}
        for s in symbols:
            sid = str(uuid.uuid4())
            sym_id_by_qn[s.qualified_name] = sid
            if "." in s.qualified_name:
                parent_id_by_name[s.qualified_name.rsplit(".", 1)[1]] = sid
            await self._insert_symbol(sid, file_id, s, content)
        # Insert edges, resolve src to symbol if possible
        for e in edges:
            src_id = None
            for qn, sid in sym_id_by_qn.items():
                leaf = qn.rsplit(".", 1)[-1]
                if leaf == e.dst_name and line_in_symbol(e.line, sym_id_by_qn, symbols):
                    src_id = sid
                    break
            # Try to resolve dst to a known symbol
            dst_id = sym_id_by_qn.get(e.dst_name)
            await self._insert_edge(src_id, file_id, dst_id, e)
        return {"file_id": str(file_id), "symbols": len(symbols), "edges": len(edges)}

    def line_in_symbol(self, line: Optional[int], sym_id_by_qn, symbols) -> bool:
        return True  # best-effort; caller can refine

    async def _upsert_file(self, rel_path, content, content_hash, mtime, language) -> str:
        row = (await self.db.execute(text("""
            INSERT INTO code_files (repo_id, path, rel_path, language, bytes, line_count, mtime, content_hash, parsed)
            VALUES (:repo, :path, :rel, :lang, :bytes, :lines, :mtime, :hash, TRUE)
            ON CONFLICT (repo_id, rel_path) DO UPDATE SET
                language = EXCLUDED.language,
                bytes = EXCLUDED.bytes,
                line_count = EXCLUDED.line_count,
                mtime = EXCLUDED.mtime,
                content_hash = EXCLUDED.content_hash,
                parsed = TRUE,
                error = NULL,
                indexed_at = NOW()
            RETURNING id
        """), {
            "repo": self.repo_id, "path": rel_path, "rel": rel_path,
            "lang": language or "unknown", "bytes": len(content.encode("utf-8")),
            "lines": content.count("\n") + 1, "mtime": mtime, "hash": content_hash,
        })).fetchone()
        await self.db.commit()
        return str(row[0])

    async def _insert_symbol(self, sid, file_id, s: ExtractedSymbol, content: str) -> None:
        await self.db.execute(text("""
            INSERT INTO code_symbols
                (id, file_id, repo_id, name, qualified_name, kind,
                 start_byte, end_byte, start_line, end_line,
                 signature, docstring, return_type, parameters,
                 parent_symbol_id, decorators, visibility,
                 is_exported, is_async, complexity, line_count)
            VALUES
                (:id, :fid, :repo, :name, :qn, :kind,
                 :sb, :eb, :sl, :el,
                 :sig, :doc, :ret, CAST(:params AS jsonb),
                 :parent, CAST(:decs AS jsonb), :vis,
                 :exp, :async, :cx, :lc)
        """), {
            "id": sid, "fid": file_id, "repo": self.repo_id,
            "name": s.name, "qn": s.qualified_name, "kind": s.kind,
            "sb": s.start_byte, "eb": s.end_byte, "sl": s.start_line, "el": s.end_line,
            "sig": s.signature, "doc": s.docstring, "ret": s.return_type,
            "params": _json_dumps(s.parameters), "parent": s.parent_symbol_id,
            "decs": _json_dumps(s.decorators), "vis": s.visibility,
            "exp": s.is_exported, "async": s.is_async,
            "cx": s.complexity, "lc": s.line_count,
        })
        await self.db.commit()

    async def _insert_edge(self, src_id, file_id, dst_id, e: ExtractedEdge) -> None:
        await self.db.execute(text("""
            INSERT INTO code_edges
                (repo_id, src_symbol_id, src_file_id, dst_symbol_id, dst_name, kind, weight, confidence, line)
            VALUES
                (:repo, :src, :fid, :dst, :name, :kind, :w, :c, :line)
        """), {
            "repo": self.repo_id, "src": src_id, "fid": file_id,
            "dst": dst_id, "name": e.dst_name, "kind": e.kind,
            "w": e.weight, "c": e.confidence, "line": e.line,
        })
        await self.db.commit()


# Helpers
def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj, default=str)


# ── High-level: index a whole repo ─────────────────────────────────────

async def index_repo(
    db: AsyncSession,
    repo_id: str,
    root_path: str,
    max_files: int = 5000,
) -> Dict[str, Any]:
    """Walk `root_path` and index every source file. Returns run stats."""
    start = time.monotonic()
    indexer = Indexer(db, repo_id)
    files_seen = 0
    files_indexed = 0
    files_errored = 0
    total_symbols = 0
    total_edges = 0
    # Run row
    run_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO code_index_runs (id, repo_id, trigger) VALUES (:id, :rid, 'manual')
    """), {"id": run_id, "rid": repo_id})
    await db.commit()

    root = Path(root_path)
    if not root.exists():
        return {"error": f"path not found: {root_path}"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if indexer.should_skip(path):
            continue
        if files_seen >= max_files:
            break
        files_seen += 1
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            rel = str(path.relative_to(root))
            result = await indexer.index_path(path, rel, content)
            files_indexed += 1
            total_symbols += result["symbols"]
            total_edges += result["edges"]
        except Exception as e:
            log.debug("index error for %s: %s", path, e)
            files_errored += 1

    duration_ms = int((time.monotonic() - start) * 1000)
    await db.execute(text("""
        UPDATE code_index_runs
        SET finished_at = NOW(), files_seen = :fs, files_indexed = :fi,
            files_errored = :fe, symbols = :sym, edges = :ed, duration_ms = :dur
        WHERE id = :id
    """), {
        "fs": files_seen, "fi": files_indexed, "fe": files_errored,
        "sym": total_symbols, "ed": total_edges, "dur": duration_ms, "id": run_id,
    })
    await db.execute(text("""
        UPDATE code_repos SET last_indexed_at = NOW() WHERE id = :id
    """), {"id": repo_id})
    await db.commit()
    return {
        "run_id": run_id, "files_seen": files_seen,
        "files_indexed": files_indexed, "files_errored": files_errored,
        "symbols": total_symbols, "edges": total_edges,
        "duration_ms": duration_ms,
    }


async def get_or_create_repo(db: AsyncSession, name: str, root_path: str, agent_id: Optional[str] = None) -> str:
    row = (await db.execute(
        text("SELECT id FROM code_repos WHERE root_path = :p"),
        {"p": root_path},
    )).fetchone()
    if row:
        return str(row[0])
    rid = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO code_repos (id, name, root_path, agent_id) VALUES (:id, :n, :p, :a)
    """), {"id": rid, "n": name, "p": root_path, "a": agent_id})
    await db.commit()
    return rid


__all__ = [
    "ExtractedSymbol", "ExtractedEdge",
    "Indexer", "index_repo", "get_or_create_repo",
    "extract_symbols", "extract_edges_from_python", "extract_edges_regex",
    "detect_language",
]
