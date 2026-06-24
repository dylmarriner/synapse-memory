import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { recallDebug, fetchAgents } from '../api/nexus';
import type { MemoryResultItem } from '../types/nexus';

function MemoryResultCard({ m, i }: { m: MemoryResultItem; i: number }) {
  const score = Math.max(0, Math.min(100, Math.round((m.score || 0) * 100)));
  const matched = (m.matched_by || []).join(', ') || 'recall';
  return (
    <div className="border border-[rgba(102,252,241,.11)] bg-[rgba(255,255,255,.025)] p-2 mb-2">
      <div className="flex items-center gap-2 text-xs">
        <span className="text-[var(--color-cyan)]">#{i + 1}</span>
        <span className="text-[var(--color-muted)]">score={m.score.toFixed(3)}</span>
        <span className="text-[var(--color-muted)]">imp={Math.round((m.importance || 0) * 100)}%</span>
        <div className="flex-1 h-1 bg-[rgba(102,252,241,.1)] ml-2">
          <div className="h-full bg-[var(--color-cyan)]" style={{ width: `${score}%` }} />
        </div>
      </div>
      <div className="text-[.65rem] text-[var(--color-dim)]">matched: {matched} · ✓{m.confirmed_count || 0} ⚠{m.contradicted_count || 0}</div>
      <div className="text-xs mt-1">{m.content?.slice(0, 300)}</div>
    </div>
  );
}

export default function RecallLab() {
  const [query, setQuery] = useState('');
  const [compareAgent, setCompareAgent] = useState('');
  const [payload, setPayload] = useState<{ q: string; agent: string | null } | null>(null);

  const { data: agents, error: agentsError } = useQuery({ queryKey: ['agents'], queryFn: fetchAgents });
  const { data: results, isFetching, error } = useQuery({
    queryKey: ['recall-lab', payload?.q, payload?.agent],
    queryFn: () => recallDebug({ query: payload!.q, agent_id: payload?.agent, limit: 8 }),
    enabled: !!payload?.q,
  });

  const modes = ['vector', 'lexical', 'graph', 'temporal'];

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Recall Lab</div>
          <h2 className="text-3xl m-0 mt-1">Mode Comparison · Fusion</h2>
        </div>
      </div>

      <div className="flex gap-3 items-center">
        <input className="flex-1 bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] p-[9px_12px] text-sm text-[var(--color-text)] outline-none"
          placeholder="Compare recall modes…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select className="bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] p-[9px_12px] text-sm text-[var(--color-text)]"
          value={compareAgent} onChange={(e) => setCompareAgent(e.target.value)}>
          <option value="">No comparison</option>
          {agents?.agents?.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
        </select>
        <button className="border border-[var(--color-cyan)] text-[var(--color-cyan)] px-4 py-2 text-sm hover:bg-[rgba(102,252,241,.08)]"
          onClick={() => setPayload({ q: query.trim(), agent: compareAgent || null })} disabled={!query.trim() || isFetching}>{isFetching ? 'Running…' : 'Run Lab'}</button>
      </div>

      {agentsError && <div className="text-[var(--color-red)] text-xs mt-2">Failed to load agents: {String(agentsError)}</div>}
      {error && <div className="text-[var(--color-red)] text-xs mt-2">Recall lab failed: {String(error)}</div>}

      {results && (
        <div className="grid grid-cols-2 gap-4 flex-1 min-h-0 mt-2 overflow-auto">
          {modes.map((mode) => (
            <div key={mode} className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-3">
              <h4 className="text-xs text-[var(--color-cyan)] uppercase tracking-[.14em] m-0 mb-2">{mode}</h4>
              {(results.per_mode?.[mode] || []).map((m, i) => <MemoryResultCard key={m.id} m={m} i={i} />)}
              {(!results.per_mode?.[mode] || results.per_mode[mode].length === 0) && <div className="text-xs text-[var(--color-dim)]">—</div>}
            </div>
          ))}
          {/* Fused */}
          <div className="border border-[var(--color-cyan)] bg-[var(--color-panel)] p-3 col-span-2">
            <h4 className="text-xs text-[var(--color-cyan)] uppercase tracking-[.14em] m-0 mb-2">Fused / Reranked</h4>
            <div className="text-[.7rem] text-[var(--color-dim)] mb-2">
              QUERY: {results.query}<br />
              EXPANDED: {results.expanded_query}<br />
              FUSION: {results.fusion}<br />
            </div>
            {(results.fused || []).map((m, i) => <MemoryResultCard key={m.id} m={m} i={i} />)}
          </div>
        </div>
      )}
      {!results && payload === null && (
        <div className="flex-1 flex items-center justify-center text-[var(--color-dim)] text-sm">
          NEXUS:// recall lab ready
        </div>
      )}
    </>
  );
}
