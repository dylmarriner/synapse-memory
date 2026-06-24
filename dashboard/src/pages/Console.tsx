import { useState } from 'react';
import { recallMemory } from '../api/nexus';
import type { BrowseMemory } from '../types/nexus';

export default function Console() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<(BrowseMemory & { score: number; modes_used: string[] })[] | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const runRecall = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError('');
    try {
      const d = await recallMemory({ query: query.trim(), limit: 8 });
      setResults(d.results.map((r) => ({ ...r, score: 0, modes_used: d.modes_used })));
    } catch (e) {
      setError(String(e));
      setResults(null);
    }
    setLoading(false);
  };

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Neural Console</div>
          <h2 className="text-3xl m-0 mt-1">Direct Recall Interface</h2>
        </div>
      </div>

      <div className="flex gap-3">
        <input className="flex-1 bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] p-[9px_12px] text-sm text-[var(--color-text)] outline-none"
          placeholder="Ask Nexus recall…" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && runRecall()} />
        <button className="border border-[var(--color-cyan)] text-[var(--color-cyan)] px-4 py-2 text-sm hover:bg-[rgba(102,252,241,.08)] disabled:opacity-30"
          onClick={runRecall} disabled={loading}>{loading ? 'recalling…' : 'Recall'}</button>
      </div>

      <div className="flex-1 border border-[rgba(102,252,241,.2)] bg-[var(--color-panel2)] p-4 overflow-auto mt-2 font-mono text-xs leading-relaxed">
        {error && <div className="text-[var(--color-red)]">NEXUS:// recall failed: {error}</div>}
        {results && (
          <>
            <div className="text-[var(--color-cyan)] mb-2">NEXUS:// recall complete — {results.length} results</div>
            {results.map((m, i) => (
              <div key={m.id} className="mb-3 border-b border-[rgba(102,252,241,.08)] pb-2">
                <span className="text-[var(--color-cyan)]">{i + 1}.</span>
                <span className="text-[var(--color-muted)]"> [{m.memory_type}]</span>
                <span className="text-[var(--color-muted)] ml-2">score={m.score?.toFixed(3)}</span>
                <div className="mt-1 text-[var(--color-text)]">{m.content}</div>
              </div>
            ))}
          </>
        )}
        {!results && !error && !loading && (
          <div className="text-[var(--color-dim)]">NEXUS:// console online<br />Type a query and run recall.</div>
        )}
      </div>
    </>
  );
}
