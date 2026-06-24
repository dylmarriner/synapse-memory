import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchMemories, fetchAgents, deleteMemory, confirmMemory, contradictMemory } from '../api/nexus';

const MEMORY_TYPES = ['', 'world', 'experience', 'observation', 'preference', 'lesson'];

export default function Vault() {
  const [query, setQuery] = useState('');
  const [type, setType] = useState('');
  const [agent, setAgent] = useState('');
  const [offset, setOffset] = useState(0);
  const qc = useQueryClient();
  const limit = 20;

  const { data: agents, error: agentsError } = useQuery({ queryKey: ['agents'], queryFn: fetchAgents });
  const { data, isLoading, error } = useQuery({
    queryKey: ['memories', query, type, agent, offset],
    queryFn: () => fetchMemories({ q: query || undefined, type: type || undefined, agent: agent || undefined, limit, offset }),
  });

  const delMut = useMutation({ mutationFn: deleteMemory, onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }) });
  const confMut = useMutation({ mutationFn: confirmMemory, onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }) });
  const contrMut = useMutation({ mutationFn: contradictMemory, onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }) });

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Memory Vault</div>
          <h2 className="text-3xl m-0 mt-1">Recall Archive</h2>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex gap-3 items-center">
        <input
          className="flex-1 bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] p-[9px_12px] text-[var(--color-text)] placeholder-[var(--color-dim)] outline-none text-sm"
          placeholder="Search the memory lattice..."
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOffset(0); }}
        />
        <select className="bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] p-[9px_12px] text-sm text-[var(--color-text)]" value={type} onChange={(e) => { setType(e.target.value); setOffset(0); }}>
          {MEMORY_TYPES.map((t) => <option key={t} value={t}>{t || 'All types'}</option>)}
        </select>
        <select className="bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] p-[9px_12px] text-sm text-[var(--color-text)]" value={agent} onChange={(e) => { setAgent(e.target.value); setOffset(0); }}>
          <option value="">All agents</option>
          {agents?.agents?.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
        </select>
      </div>

      {agentsError && <div className="text-[var(--color-red)] text-xs">Failed to load agents: {String(agentsError)}</div>}
      {error && <div className="text-[var(--color-red)] text-xs">Failed to load memories: {String(error)}</div>}

      {/* Results */}
      <div className="flex-1 overflow-auto space-y-2 min-h-0 mt-2">
        {isLoading && <div className="text-[var(--color-dim)] text-center py-8">Loading memory signatures…</div>}
        {data?.memories?.map((m) => (
          <div key={m.id} className="border border-[rgba(102,252,241,.11)] bg-[rgba(255,255,255,.025)] p-3">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[.7rem] px-2 py-0.5 border border-[rgba(102,252,241,.22)] uppercase tracking-[.1em] text-[var(--color-cyan)]">{m.memory_type}</span>
              <span className="text-xs text-[var(--color-muted)]">{m.agent_name}</span>
              <span className="text-xs text-[var(--color-dim)] ml-auto">{m.created_at ? new Date(m.created_at).toLocaleString() : ''}</span>
            </div>
            <div className="text-sm leading-relaxed">{m.content}</div>
            <div className="flex items-center gap-3 mt-1 text-xs text-[var(--color-muted)]">
              <span>importance {Math.round(m.importance * 100)}%</span>
              <span>accessed {m.access_count}x</span>
              {m.confirmed_count > 0 && <span className="text-[var(--color-green)]">✓ {m.confirmed_count}</span>}
              {m.contradicted_count > 0 && <span className="text-[var(--color-red)]">⚠ {m.contradicted_count}</span>}
              <button className="ml-auto text-[var(--color-red)] hover:underline" onClick={() => { if (window.confirm('Delete this memory?')) delMut.mutate(m.id); }}>Delete</button>
              <button className="text-[var(--color-green)] hover:underline" onClick={() => confMut.mutate(m.id)}>✓</button>
              <button className="text-[var(--color-amber)] hover:underline" onClick={() => contrMut.mutate(m.id)}>⚠</button>
            </div>
          </div>
        ))}
        {!isLoading && !error && (!data?.memories || data.memories.length === 0) && (
          <div className="text-[var(--color-dim)] text-center py-8">No memory signatures found.</div>
        )}
      </div>

      {/* Pagination */}
      {data && data.total > limit && (
        <div className="flex justify-center gap-3 items-center text-xs">
          <button className="border border-[rgba(102,252,241,.22)] px-3 py-1 disabled:opacity-30" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>← Prev</button>
          <span className="text-[var(--color-muted)]">Sector {Math.floor(offset / limit) + 1}/{Math.ceil(data.total / limit)} · {data.total} records</span>
          <button className="border border-[rgba(102,252,241,.22)] px-3 py-1 disabled:opacity-30" disabled={offset + limit >= data.total} onClick={() => setOffset(offset + limit)}>Next →</button>
        </div>
      )}
    </>
  );
}
