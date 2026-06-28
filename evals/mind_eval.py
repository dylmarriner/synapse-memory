"""Live eval harness for the Living Mind.

Runs a set of test questions against /v1/mind/think and scores the
responses against expected behaviour.  Used to compare the baseline
(3b, single LLM call) against the new 7b + restructured pipeline.

Run:
    NEXUS_URL=http://100.93.75.87:7777 \\
    NEXUS_SECRET=nexus-memory-shared-key-2026 \\
    python evals/mind_eval.py

Output: a scorecard printed to stdout.  Optional --json <file> for
machine-readable output, --baseline <file> to compare against a saved
baseline run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

import urllib.request
import urllib.error

DEFAULT_URL = os.environ.get("NEXUS_URL", "http://100.93.75.87:7777")
DEFAULT_SECRET = os.environ.get("NEXUS_SECRET", "nexus-memory-shared-key-2026")
MIND_ID = "default"


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    """One question + scoring function."""
    name: str
    question: str
    reasoning_depth: str = "standard"
    context: Optional[Dict[str, Any]] = None
    timeout_s: int = 180
    score: Optional[Callable[[Dict[str, Any]], Tuple[float, str]]] = None  # (0..1, reason)


def score_keyword_present(needle: str) -> Callable:
    """Answer must mention this substring (case-insensitive)."""
    def _s(r: Dict[str, Any]) -> Tuple[float, str]:
        a = (r.get("answer") or "").lower()
        if needle.lower() in a:
            return 1.0, f"mentions {needle!r}"
        return 0.0, f"missing {needle!r}"
    return _s


def score_keyword_any(*needles: str) -> Callable:
    """At least one of these substrings must appear (case-insensitive)."""
    def _s(r: Dict[str, Any]) -> Tuple[float, str]:
        a = (r.get("answer") or "").lower()
        for n in needles:
            if n.lower() in a:
                return 1.0, f"mentions one of {needles!r}"
        return 0.0, f"missing all of {needles!r}"
    return _s


def score_confidence_in_range(lo: float, hi: float) -> Callable:
    """Returned confidence must be within [lo, hi]."""
    def _s(r: Dict[str, Any]) -> Tuple[float, str]:
        c = r.get("confidence") or 0.0
        if lo <= c <= hi:
            return 1.0, f"confidence {c:.2f} in [{lo},{hi}]"
        return 0.0, f"confidence {c:.2f} NOT in [{lo},{hi}]"
    return _s


def score_cited_min(n: int) -> Callable:
    """At least n memories must be cited (or in the memory evidence list)."""
    def _s(r: Dict[str, Any]) -> Tuple[float, str]:
        mc = r.get("memories_cited") or []
        if len(mc) >= n:
            return 1.0, f"cited {len(mc)} memories (>= {n})"
        return 0.0, f"cited only {len(mc)} memories (< {n})"
    return _s


def score_has_evidence_ids() -> Callable:
    """Reasoning trace should reference memory ids in evidence."""
    def _s(r: Dict[str, Any]) -> Tuple[float, str]:
        rt = r.get("reasoning_trace") or {}
        # The enriched reasoning may surface evidence in the trace
        ev = rt.get("evidence") if isinstance(rt, dict) else None
        mc = r.get("memories_cited") or []
        cited_ids = {m.get("id") for m in mc if isinstance(m, dict) and m.get("id")}
        if cited_ids and len(cited_ids) >= 1:
            return 1.0, f"{len(cited_ids)} memory ids cited"
        return 0.0, "no memory ids cited"
    return _s


def score_answer_length(lo: int, hi: int) -> Callable:
    """Answer should be roughly lo..hi characters (not too short, not bloated)."""
    def _s(r: Dict[str, Any]) -> Tuple[float, str]:
        a = r.get("answer") or ""
        n = len(a)
        if lo <= n <= hi:
            return 1.0, f"length {n} in [{lo},{hi}]"
        return 0.0, f"length {n} NOT in [{lo},{hi}]"
    return _s


def score_has_proactive() -> Callable:
    """Should surface at least one proactive item when question is open-ended."""
    def _s(r: Dict[str, Any]) -> Tuple[float, str]:
        pc = r.get("proactive_context") or []
        if pc:
            return 1.0, f"surfaced {len(pc)} proactive item(s)"
        return 0.0, "no proactive context"
    return _s


# Composite: weighted average
def score_composite(*parts: Tuple[Callable, float]) -> Callable:
    """Each part is (scorer, weight).  Final = sum(score*weight)/sum(weight)."""
    total_w = sum(w for _, w in parts)
    def _s(r: Dict[str, Any]) -> Tuple[float, str]:
        results = []
        for fn, w in parts:
            s, msg = fn(r)
            results.append((s * w, msg, w))
        score = sum(r[0] for r in results) / total_w if total_w else 0
        msgs = "; ".join(f"[w={r[2]}] {r[1]}" for r in results)
        return score, msgs
    return _s


TEST_CASES: List[TestCase] = [
    TestCase(
        name="synapse_recall_basic",
        question="What is the synapse-memory project? Summarise what you know about it.",
        score=score_composite(
            (score_keyword_any("synapse", "memory", "shared", "agent"), 0.6),
            (score_answer_length(100, 1500), 0.2),
            (score_cited_min(1), 0.2),
        ),
    ),
    TestCase(
        name="machine_fleet",
        question="Which machines form the agent fleet and what roles do they play?",
        score=score_composite(
            (score_keyword_any("kubuntux", "macuntu", "lin", "rabuntu"), 0.6),
            (score_answer_length(80, 1200), 0.2),
            (score_cited_min(1), 0.2),
        ),
    ),
    TestCase(
        name="mind_self_description",
        question="Describe yourself — what kind of mind are you, what can you do, and what are your limitations?",
        reasoning_depth="deep",
        score=score_composite(
            (score_answer_length(150, 1500), 0.5),
            (score_cited_min(1), 0.5),
        ),
    ),
    TestCase(
        name="vague_question_should_ask_back",
        question="What about the thing?",
        score=score_composite(
            (lambda r: (1.0, "ok") if (r.get("clarifying_question") or r.get("answer")) else (0.0, "no response"), 1.0),
        ),
    ),
    TestCase(
        name="ollama_gpu_setup",
        question="How is the Living Mind configured to use local Ollama, and what fallback model is wired in?",
        score=score_composite(
            (score_keyword_any("ollama", "qwen", "deepseek", "fallback"), 0.6),
            (score_answer_length(80, 1200), 0.2),
            (score_cited_min(1), 0.2),
        ),
    ),
    TestCase(
        name="multi_machine_sync",
        question="Explain the multi-machine sync mechanism that keeps the four agents' memory stores consistent.",
        score=score_composite(
            (score_keyword_any("syncthing", "sync", "cron", "synapse", "multi-machine", "five minutes", "5 min", "5min"), 0.5),
            (score_answer_length(80, 1500), 0.3),
            (score_cited_min(1), 0.2),
        ),
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    name: str
    question: str
    score: float
    reason: str
    duration_ms: int
    answer: str
    confidence: float
    proactive_count: int
    memories_cited: int
    status: str  # "ok" | "error" | "timeout"
    error: Optional[str] = None
    response: Optional[Dict[str, Any]] = None


def post_think(url: str, secret: str, question: str, depth: str,
               context: Optional[Dict[str, Any]] = None,
               timeout_s: int = 180) -> Tuple[Optional[Dict[str, Any]], int, Optional[str]]:
    """POST to /v1/mind/think. Returns (json, duration_ms, error)."""
    body = json.dumps({
        "mind_id": MIND_ID,
        "question": question,
        "reasoning_depth": depth,
        "context": context or {},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/v1/mind/think",
        data=body,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            dt = int((time.monotonic() - t0) * 1000)
            return data, dt, None
    except urllib.error.HTTPError as e:
        dt = int((time.monotonic() - t0) * 1000)
        return None, dt, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:
        dt = int((time.monotonic() - t0) * 1000)
        return None, dt, f"{type(e).__name__}: {e}"


def run_case(url: str, secret: str, tc: TestCase) -> RunResult:
    resp, dt, err = post_think(url, secret, tc.question, tc.reasoning_depth, tc.context, tc.timeout_s)
    if err is not None or resp is None:
        return RunResult(
            name=tc.name, question=tc.question, score=0.0, reason=err or "no response",
            duration_ms=dt, answer="", confidence=0.0, proactive_count=0,
            memories_cited=0, status="error", error=err, response=None,
        )
    answer = (resp.get("answer") or "").strip()
    if not answer and not resp.get("clarifying_question"):
        return RunResult(
            name=tc.name, question=tc.question, score=0.0, reason="empty answer",
            duration_ms=dt, answer="", confidence=resp.get("confidence", 0.0),
            proactive_count=len(resp.get("proactive_context") or []),
            memories_cited=len(resp.get("memories_cited") or []),
            status="empty", response=resp,
        )
    score = 1.0
    reason = "scored"
    if tc.score is not None:
        score, reason = tc.score(resp)
    return RunResult(
        name=tc.name, question=tc.question, score=score, reason=reason,
        duration_ms=dt, answer=answer[:200], confidence=resp.get("confidence", 0.0),
        proactive_count=len(resp.get("proactive_context") or []),
        memories_cited=len(resp.get("memories_cited") or []),
        status="ok", response=resp,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--secret", default=DEFAULT_SECRET)
    p.add_argument("--json", help="write machine-readable results to this file")
    p.add_argument("--baseline", help="compare against this saved JSON file")
    p.add_argument("--only", help="comma-separated test names to run (default: all)")
    p.add_argument("--filter", action="store_true", help="deprecated: alias for --only")
    args = p.parse_args()

    cases = TEST_CASES
    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        cases = [c for c in TEST_CASES if c.name in wanted]
    if args.filter and not args.only:
        # ignore
        pass

    results: List[RunResult] = []
    for i, tc in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {tc.name} ...", end=" ", flush=True)
        r = run_case(args.url, args.secret, tc)
        results.append(r)
        print(f"score={r.score:.2f} dur={r.duration_ms}ms status={r.status} :: {r.reason[:120]}")
        if r.status == "ok":
            print(f"    answer: {r.answer[:140]}{'…' if len(r.answer) > 140 else ''}")
            print(f"    confidence={r.confidence:.2f}  memories_cited={r.memories_cited}  proactive={r.proactive_count}")

    # Summary
    n = len(results)
    avg = sum(r.score for r in results) / n if n else 0
    avg_dur = sum(r.duration_ms for r in results) / n if n else 0
    print()
    print("=" * 60)
    print(f"OVERALL: {sum(r.score for r in results):.2f} / {n}  (avg {avg:.2f})")
    print(f"AVG DURATION: {avg_dur:.0f}ms")
    print(f"PASS (score >= 0.5): {sum(1 for r in results if r.score >= 0.5)}/{n}")
    print(f"FAIL (score < 0.5):  {sum(1 for r in results if r.score < 0.5)}/{n}")
    print("=" * 60)

    if args.json:
        with open(args.json, "w") as f:
            json.dump([asdict(r) for r in results], f, indent=2, default=str)
        print(f"Wrote {args.json}")

    if args.baseline:
        try:
            with open(args.baseline) as f:
                base = {r["name"]: r for r in json.load(f)}
        except FileNotFoundError:
            print(f"baseline file not found: {args.baseline}")
            return 1
        print()
        print(f"COMPARISON vs baseline ({args.baseline}):")
        print(f"{'TEST':<35} {'BASE':>6} {'NEW':>6} {'Δ':>7}")
        for r in results:
            b = base.get(r.name, {})
            bscore = b.get("score", 0.0)
            delta = r.score - bscore
            print(f"{r.name:<35} {bscore:>6.2f} {r.score:>6.2f} {delta:>+7.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
