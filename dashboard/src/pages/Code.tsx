import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchCodeStats, indexCodeRepo, searchCodeSymbols,
  getCodeSymbolCard, blastRadius,
  generateWiki, fetchWikiIndex, fetchWikiArticle,
} from '../api/nexus';

const RUNG_LABELS = ['1 · metadata', '2 · card', '3 · hot path', '4 · full source'];

function Stat({ label, value, color = 'cyan', sub }: { label: string; value: string | number; color?: string; sub?: string }) {
  return (
    <div className="nx-card relative overflow-hidden">
      <div className="absolute -right-5 -top-5 w-14 h-14 border rotate-45" style={{ borderColor: 'rgba(102,252,241,0.18)' }} />
      <div className="text-[.6rem] text-[var(--color-muted)] uppercase tracking-[.22em]">{label}</div>
      <div className="text-2xl tabular-nums mt-1" style={{ color: `var(--color-${color})` }}>{value}</div>
      {sub && <div className="text-[.55rem] text-[var(--color-dim)] mt-0.5">{sub}</div>}
    </div>
  );
}

function KindBadge({ kind }: { kind: string }) {
  const colorMap: Record<string, string> = {
    function: 'var(--color-cyan)',
    method: 'var(--color-cyan)',
    class: 'var(--color-violet)',
    variable: 'var(--color-amber)',
    constant: 'var(--color-amber)',
    interface: 'var(--color-green)',
    module: 'var(--color-magenta)',
  };
  return (
    <span className="text-[.6rem] uppercase tracking-[.14em] px-1.5 py-0.5 border"
      style={{ borderColor: (colorMap[kind] || 'var(--color-muted)') + '88', color: colorMap[kind] || 'var(--color-muted)' }}>
      {kind}
    </span>
  );
}

export default function Code() {
  const qc = useQueryClient();
  const [query, setQuery] = useState('');
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [rung, setRung] = useState<2 | 3 | 4>(2);
  const [justification, setJustification] = useState('');
  const [blastTarget, setBlastTarget] = useState('');
  const [wikiArticle, setWikiArticle] = useState<string | null>(null);
  const [indexPath, setIndexPath] = useState('/app');

  const stats = useQuery({ queryKey: ['code-stats'], queryFn: fetchCodeStats, refetchInterval: 30000 });
  const search = useQuery({
    queryKey: ['code-search', query],
    queryFn: () => searchCodeSymbols(query),
    enabled: query.length >= 2,
  });
  const card = useQuery({
    queryKey: ['code-card', selectedSymbol, rung],
    queryFn: () => getCodeSymbolCard(selectedSymbol!, rung >= 3),
    enabled: !!selectedSymbol,
  });
  const blast = useQuery({
    queryKey: ['code-blast', blastTarget],
    queryFn: () => blastRadius(blastTarget, 2),
    enabled: blastTarget.length >= 2,
  });
  const wikiIndex = useQuery({ queryKey: ['wiki-index'], queryFn: fetchWikiIndex, refetchInterval: 60000 });
  const wikiDoc = useQuery({
    queryKey: ['wiki-article', wikiArticle],
    queryFn: () => fetchWikiArticle(wikiArticle!),
    enabled: !!wikiArticle,
  });

  const reindexMut = useMutation({
    mutationFn: () => indexCodeRepo('nexus-self', indexPath),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['code-stats'] }),
  });
  const wikiMut = useMutation({
    mutationFn: generateWiki,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['wiki-index'] }),
  });

  return (
    <div className="flex flex-col gap-3 h-full">
      <div className="flex items-end gap-3">
        <div>
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.34em]">Code Context</div>
          <h2 className="text-3xl m-0 mt-1 nx-glow" style={{ color: 'var(--color-green)' }}>
            IRIS GATE
          </h2>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[.62rem] text-[var(--color-muted)] uppercase tracking-[.16em]">
            indexed
          </span>
          {stats.data && (
            <span className="text-[.7rem] tabular-nums text-[var(--color-green)]">
              {stats.data.symbols.toLocaleString()} sym · {stats.data.edges.toLocaleString()} edges
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-5 gap-2">
        <Stat label="files" value={stats.data?.files ?? '...'} sub="indexed" />
        <Stat label="symbols" value={stats.data?.symbols.toLocaleString() ?? '...'} color="violet" sub="functions + classes" />
        <Stat label="edges" value={stats.data?.edges.toLocaleString() ?? '...'} color="amber" sub="call + import" />
        <Stat label="languages" value={stats.data?.languages ?? '...'} color="magenta" sub="distinct" />
        <Stat label="wiki" value={stats.data?.wiki_articles ?? '...'} color="green" sub="articles" />
      </div>

      <div className="grid grid-cols-[1.3fr_1fr] gap-3 flex-1 min-h-0">
        {/* LEFT: search + symbol card + blast radius */}
        <div className="flex flex-col gap-3 min-h-0">
          {/* Search */}
          <div className="nx-card">
            <div className="flex gap-2 mb-2">
              <input
                className="flex-1 bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] px-2 py-1.5 text-[.8rem] text-[var(--color-text)] outline-none"
                placeholder="search symbols by name (e.g. LivingMind.think)…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="space-y-1 max-h-48 overflow-auto">
              {search.isLoading && <div className="text-[var(--color-dim)] text-[.7rem]">searching…</div>}
              {search.data?.symbols.map((s) => (
                <button
                  key={s.id}
                  onClick={() => { setSelectedSymbol(s.qualified_name); setBlastTarget(s.qualified_name); }}
                  className={`w-full text-left p-2 border ${selectedSymbol === s.qualified_name ? 'border-[var(--color-cyan)] bg-[rgba(102,252,241,.06)]' : 'border-[var(--color-line)] hover:border-[var(--color-cyan)]'} transition-colors`}
                >
                  <div className="flex items-center gap-2">
                    <KindBadge kind={s.kind} />
                    <span className="nx-mono text-[.75rem] text-[var(--color-text)] truncate flex-1">
                      {s.qualified_name}
                    </span>
                    <span className="text-[.55rem] text-[var(--color-dim)]">
                      L{s.start_line}-{s.end_line}
                    </span>
                  </div>
                  {s.docstring && (
                    <div className="text-[.6rem] text-[var(--color-muted)] mt-0.5 truncate">
                      {s.docstring.split('\n')[0]}
                    </div>
                  )}
                </button>
              ))}
              {search.data && search.data.symbols.length === 0 && (
                <div className="text-[var(--color-dim)] text-[.7rem] text-center py-3">no symbols match</div>
              )}
            </div>
          </div>

          {/* Selected symbol card */}
          {selectedSymbol && (
            <div className="nx-card flex-1 min-h-0 overflow-auto">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[.7rem] text-[var(--color-cyan)] uppercase tracking-[.18em]">Symbol Card</span>
                <KindBadge kind={card.data?.kind ?? '...'} />
                <span className="ml-auto text-[.6rem] text-[var(--color-dim)]">
                  {card.data?.complexity ?? 0} cyclomatic · {card.data?.line_count ?? 0} lines
                </span>
              </div>
              {card.isLoading && <div className="text-[var(--color-dim)] text-[.7rem]">fetching…</div>}
              {card.data && (
                <>
                  <div className="nx-mono text-[.8rem] text-[var(--color-green)] break-all mb-1">
                    {card.data.qualified_name}
                  </div>
                  <div className="text-[.6rem] text-[var(--color-muted)] mb-2 italic">
                    {card.data.signature}
                  </div>
                  {card.data.docstring && (
                    <div className="text-[.7rem] text-[var(--color-text)] mb-2">
                      {card.data.docstring}
                    </div>
                  )}
                  {card.data.parameters.length > 0 && (
                    <div className="text-[.65rem] text-[var(--color-muted)] mb-1">
                      <span className="text-[var(--color-amber)]">params:</span>{' '}
                      {card.data.parameters.map(p => p.name).join(', ')}
                    </div>
                  )}
                  {card.data.return_type && (
                    <div className="text-[.65rem] text-[var(--color-muted)] mb-1">
                      <span className="text-[var(--color-amber)]">returns:</span> {card.data.return_type}
                    </div>
                  )}
                  <div className="text-[.6rem] text-[var(--color-dim)] mb-3">
                    📁 {card.data.location.path}:{card.data.location.start_line}-{card.data.location.end_line}
                  </div>
                  {card.data.source_snippet && (
                    <pre className="nx-mono text-[.65rem] leading-relaxed text-[var(--color-green)] bg-black/40 p-2 border border-[var(--color-line)] overflow-auto max-h-72 whitespace-pre">
                      {card.data.source_snippet}
                    </pre>
                  )}
                </>
              )}
            </div>
          )}

          {/* Blast radius */}
          {selectedSymbol && blast.data && (
            <div className="nx-card">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[.7rem] text-[var(--color-magenta)] uppercase tracking-[.18em]">Blast Radius</span>
                <span className="ml-auto text-[.6rem] text-[var(--color-dim)]">
                  {blast.data.total_affected} symbols affected
                </span>
              </div>
              <div className="flex gap-2 text-[.65rem] mb-2">
                {Object.entries(blast.data.by_depth).map(([d, n]) => (
                  <div key={d} className="px-2 py-1 border border-[var(--color-line)]">
                    <span className="text-[var(--color-cyan)]">depth {d}:</span> {n}
                  </div>
                ))}
              </div>
              <div className="space-y-0.5 max-h-40 overflow-auto">
                {blast.data.symbols.slice(0, 15).map((s, i) => (
                  <div key={i} className="text-[.65rem] flex items-center gap-2">
                    <span className="text-[var(--color-dim)] w-8">d={s.depth}</span>
                    <KindBadge kind={s.symbol.kind} />
                    <span className="nx-mono text-[var(--color-text)] truncate flex-1">
                      {s.symbol.qualified_name}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT: Iris Gate controls + wiki */}
        <div className="flex flex-col gap-3 min-h-0">
          {/* Iris Gate */}
          <div className="nx-card">
            <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.18em] mb-2">
              Iris Gate Ladder
            </div>
            <div className="text-[.6rem] text-[var(--color-muted)] mb-2">
              4-rung context escalation. Start at rung 1, escalate only when you need more.
            </div>
            <div className="flex gap-1 mb-2">
              {RUNG_LABELS.map((l, i) => (
                <button
                  key={i}
                  onClick={() => setRung((i + 1) as 2 | 3 | 4)}
                  className={`flex-1 px-2 py-1.5 text-[.6rem] uppercase tracking-[.12em] border transition-all ${
                    rung === i + 1
                      ? 'border-[var(--color-cyan)] text-[var(--color-cyan)]'
                      : 'border-[var(--color-line)] text-[var(--color-muted)] hover:border-[var(--color-cyan)]'
                  }`}
                >
                  {l}
                </button>
              ))}
            </div>
            {rung === 4 && (
              <input
                className="w-full bg-[rgba(255,60,172,.045)] border border-[rgba(255,60,172,.22)] px-2 py-1 text-[.7rem] text-[var(--color-text)] outline-none mb-2"
                placeholder="justification required for rung 4 (e.g. 'debugging import error')…"
                value={justification}
                onChange={(e) => setJustification(e.target.value)}
              />
            )}
            {selectedSymbol && (
              <button
                onClick={async () => {
                  qc.invalidateQueries({ queryKey: ['code-card', selectedSymbol, rung] });
                }}
                className="w-full px-3 py-1.5 text-[.7rem] uppercase tracking-[.14em] border border-[var(--color-cyan)] text-[var(--color-cyan)] hover:bg-[rgba(102,252,241,.08)] disabled:opacity-30"
              >
                Fetch rung {rung}
              </button>
            )}
          </div>

          {/* Wiki */}
          <div className="nx-card flex-1 min-h-0 overflow-auto">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[.62rem] text-[var(--color-amber)] uppercase tracking-[.18em]">
                Wiki
              </span>
              <span className="text-[.6rem] text-[var(--color-dim)]">
                {wikiIndex.data?.count ?? 0} articles
              </span>
              <button
                onClick={() => wikiMut.mutate()}
                disabled={wikiMut.isPending}
                className="ml-auto px-2 py-1 text-[.6rem] uppercase tracking-[.12em] border border-[var(--color-amber)] text-[var(--color-amber)] hover:bg-[rgba(255,209,102,.08)] disabled:opacity-30"
              >
                {wikiMut.isPending ? 'generating…' : 'regenerate'}
              </button>
            </div>
            <div className="space-y-0.5">
              {wikiIndex.data?.articles.map((a) => (
                <button
                  key={a.slug}
                  onClick={() => setWikiArticle(a.slug)}
                  className={`w-full text-left px-2 py-1 text-[.7rem] border ${
                    wikiArticle === a.slug ? 'border-[var(--color-amber)] bg-[rgba(255,209,102,.06)]' : 'border-transparent hover:border-[var(--color-line)]'
                  } transition-colors flex items-center gap-2`}
                >
                  <span className="text-[var(--color-amber)]">▸</span>
                  <span className="flex-1 text-[var(--color-text)]">{a.title}</span>
                  <span className="text-[.55rem] text-[var(--color-dim)]">~{a.tokens} tok</span>
                </button>
              ))}
            </div>
            {wikiDoc.data && (
              <div className="mt-3 pt-3 border-t border-[var(--color-line)] max-h-72 overflow-auto">
                <div className="text-[.7rem] text-[var(--color-amber)] uppercase tracking-[.16em] mb-1">
                  {wikiDoc.data.title}
                </div>
                <pre className="nx-mono text-[.65rem] leading-relaxed text-[var(--color-text)] whitespace-pre-wrap">
                  {wikiDoc.data.content}
                </pre>
              </div>
            )}
          </div>

          {/* Indexer */}
          <div className="nx-card">
            <div className="text-[.62rem] text-[var(--color-violet)] uppercase tracking-[.18em] mb-2">
              Re-index
            </div>
            <input
              className="w-full bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] px-2 py-1 text-[.7rem] text-[var(--color-text)] outline-none mb-2"
              value={indexPath}
              onChange={(e) => setIndexPath(e.target.value)}
            />
            <button
              onClick={() => reindexMut.mutate()}
              disabled={reindexMut.isPending}
              className="w-full px-3 py-1.5 text-[.7rem] uppercase tracking-[.14em] border border-[var(--color-violet)] text-[var(--color-violet)] hover:bg-[rgba(185,103,255,.08)] disabled:opacity-30"
            >
              {reindexMut.isPending ? 'indexing…' : `Re-index ${indexPath}`}
            </button>
            {reindexMut.data && (
              <div className="text-[.65rem] text-[var(--color-green)] mt-1">
                ✓ {reindexMut.data.files_indexed} files · {reindexMut.data.symbols} symbols · {reindexMut.data.duration_ms}ms
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
