import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchMemories, fetchAgents, deleteMemory, confirmMemory, contradictMemory } from '../api/nexus';
import type { AgentSummary } from '../types/nexus';

const MEMORY_TYPES = ['', 'world', 'experience', 'observation', 'preference', 'lesson'];

const TYPE_COLORS: Record<string, string> = {
  world: '#66fcf1',
  experience: '#b967ff',
  observation: '#ff3cac',
  preference: '#ffd166',
  lesson: '#63ff9f',
};

const TYPE_GLYPHS: Record<string, string> = {
  world: '◆',
  experience: '✦',
  observation: '◉',
  preference: '✧',
  lesson: '◈',
};

function ago(iso: string | null) {
  if (!iso) return '—';
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export default function Lattice() {
  const [query, setQuery] = useState('');
  const [type, setType] = useState('');
  const [agent, setAgent] = useState('');
  const [offset, setOffset] = useState(0);
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const qc = useQueryClient();
  const limit = 24;

  const { data: agents } = useQuery({ queryKey: ['agents'], queryFn: fetchAgents });
  const { data, isLoading } = useQuery({
    queryKey: ['lattice-mems', query, type, agent, offset],
    queryFn: () => fetchMemories({ q: query || undefined, type: type || undefined, agent: agent || undefined, limit, offset }),
  });

  const delMut = useMutation({ mutationFn: deleteMemory, onSuccess: () => qc.invalidateQueries({ queryKey: ['lattice-mems'] }) });
  const confMut = useMutation({ mutationFn: confirmMemory, onSuccess: () => qc.invalidateQueries({ queryKey: ['lattice-mems'] }) });
  const contrMut = useMutation({ mutationFn: contradictMemory, onSuccess: () => qc.invalidateQueries({ queryKey: ['lattice-mems'] }) });

  const mems = data?.memories ?? [];

  return (
    <div className="flex flex-col gap-3 h-full">
      <div className="flex items-end gap-3">
        <div>
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.34em]">Memory Archive</div>
          <h2 className="text-3xl m-0 mt-1 nx-glow" style={{ color: 'var(--color-cyan)' }}>CRYSTAL LATTICE</h2>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <button onClick={() => setView('grid')} className={`px-2 py-1 text-[.65rem] border uppercase tracking-[.16em] ${view === 'grid' ? 'border-[var(--color-cyan)] text-[var(--color-cyan)]' : 'border-[var(--color-line)] text-[var(--color-muted)]'}`}>◬ grid</button>
          <button onClick={() => setView('list')} className={`px-2 py-1 text-[.65rem] border uppercase tracking-[.16em] ${view === 'list' ? 'border-[var(--color-cyan)] text-[var(--color-cyan)]' : 'border-[var(--color-line)] text-[var(--color-muted)]'}`}>☰ list</button>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex gap-2 items-center">
        <input
          className="flex-1 bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] px-3 py-2 text-[.85rem] text-[var(--color-text)] placeholder-[var(--color-dim)] outline-none"
          placeholder="Search the memory lattice…"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOffset(0); }}
        />
        <select className="bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] px-2 py-2 text-[.75rem] text-[var(--color-text)]" value={type} onChange={(e) => { setType(e.target.value); setOffset(0); }}>
          {MEMORY_TYPES.map((t) => <option key={t} value={t}>{t || 'all types'}</option>)}
        </select>
        <select className="bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] px-2 py-2 text-[.75rem] text-[var(--color-text)]" value={agent} onChange={(e) => { setAgent(e.target.value); setOffset(0); }}>
          <option value="">all agents</option>
          {(agents?.agents ?? []).map((a: AgentSummary) => <option key={a.name} value={a.name}>{a.name}</option>)}
        </select>
      </div>

      {/* Memories */}
      <div className="flex-1 overflow-auto min-h-0">
        {isLoading && <div className="text-center py-8 text-[var(--color-dim)] text-sm">Loading memory crystals…</div>}
        {view === 'grid' ? (
          <div className="grid grid-cols-3 gap-2">
            {mems.map((m) => {
              const c = TYPE_COLORS[m.memory_type] ?? '#66fcf1';
              const g = TYPE_GLYPHS[m.memory_type] ?? '◆';
              return (
                <div key={m.id} className="nx-card relative overflow-hidden group" style={{ minHeight: 140 }}>
                  <div className="absolute -right-4 -top-4 w-12 h-12 border rotate-45" style={{ borderColor: c + '44' }} />
                  <div className="absolute -right-3 -bottom-3 w-6 h-6 border-dashed border rotate-12" style={{ borderColor: c + '22' }} />
                  <div className="flex items-center gap-1.5 mb-1.5 flex-wrap">
                    <span className="text-[1.1rem]" style={{ color: c, textShadow: `0 0 6px ${c}` }}>{g}</span>
                    <span className="nx-tag" style={{ borderColor: c + '88', color: c }}>{m.memory_type}</span>
                    {m.confirmed_count > 0 && <span className="text-[.55rem] text-[var(--color-green)]">✓{m.confirmed_count}</span>}
                    {m.contradicted_count > 0 && <span className="text-[.55rem] text-[var(--color-red)]">⚠{m.contradicted_count}</span>}
                    <span className="ml-auto text-[.6rem] text-[var(--color-dim)] tabular-nums">{ago(m.created_at)}</span>
                  </div>
                  <div className="text-[.8rem] text-[var(--color-text)] leading-relaxed line-clamp-4">{m.content}</div>
                  <div className="flex items-center gap-3 mt-1.5 text-[.6rem] text-[var(--color-muted)]">
                    <span className="text-[var(--color-violet)]">{m.agent_name ?? '—'}</span>
                    <span>imp {(m.importance * 100).toFixed(0)}%</span>
                    <span>×{m.access_count ?? 0}</span>
                    <div className="ml-auto flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => confMut.mutate(m.id)} className="text-[var(--color-green)] hover:underline">✓</button>
                      <button onClick={() => contrMut.mutate(m.id)} className="text-[var(--color-amber)] hover:underline">⚠</button>
                      <button onClick={() => { if (window.confirm('Delete?')) delMut.mutate(m.id); }} className="text-[var(--color-red)] hover:underline">×</button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="space-y-1.5">
            {mems.map((m) => {
              const c = TYPE_COLORS[m.memory_type] ?? '#66fcf1';
              return (
                <div key={m.id} className="border border-[var(--color-line)] bg-[rgba(255,255,255,.02)] p-2 flex items-start gap-2 hover:border-[var(--color-cyan)] hover:bg-[rgba(102,252,241,.04)] transition-colors">
                  <span className="text-[1.1rem] shrink-0" style={{ color: c, textShadow: `0 0 6px ${c}` }}>{TYPE_GLYPHS[m.memory_type] ?? '◆'}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                      <span className="nx-tag" style={{ borderColor: c + '88', color: c }}>{m.memory_type}</span>
                      <span className="text-[.7rem] text-[var(--color-violet)]">{m.agent_name ?? '—'}</span>
                      {m.confirmed_count > 0 && <span className="text-[.55rem] text-[var(--color-green)]">✓{m.confirmed_count}</span>}
                      <span className="ml-auto text-[.6rem] text-[var(--color-dim)] tabular-nums">{ago(m.created_at)}</span>
                    </div>
                    <div className="text-[.78rem] text-[var(--color-text)] leading-relaxed">{m.content}</div>
                  </div>
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    <span className="text-[.6rem] text-[var(--color-muted)]">imp {(m.importance * 100).toFixed(0)}%</span>
                    <span className="text-[.6rem] text-[var(--color-muted)]">×{m.access_count}</span>
                    <div className="flex gap-1.5 mt-0.5">
                      <button onClick={() => confMut.mutate(m.id)} className="text-[var(--color-green)] hover:underline text-[.7rem]">✓</button>
                      <button onClick={() => contrMut.mutate(m.id)} className="text-[var(--color-amber)] hover:underline text-[.7rem]">⚠</button>
                      <button onClick={() => { if (window.confirm('Delete?')) delMut.mutate(m.id); }} className="text-[var(--color-red)] hover:underline text-[.7rem]">×</button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {!isLoading && mems.length === 0 && (
          <div className="text-center py-8 text-[var(--color-dim)]">No memory crystals match the current filters.</div>
        )}
      </div>

      {/* Pagination */}
      {data && data.total > limit && (
        <div className="flex justify-center gap-3 items-center text-xs border-t border-[var(--color-line)] pt-2">
          <button className="border border-[rgba(102,252,241,.22)] px-3 py-1 disabled:opacity-30 hover:border-[var(--color-cyan)]" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>← prev</button>
          <span className="text-[var(--color-muted)]">sector {Math.floor(offset / limit) + 1}/{Math.ceil(data.total / limit)} · {data.total} records</span>
          <button className="border border-[rgba(102,252,241,.22)] px-3 py-1 disabled:opacity-30 hover:border-[var(--color-cyan)]" disabled={offset + limit >= data.total} onClick={() => setOffset(offset + limit)}>next →</button>
        </div>
      )}
    </div>
  );
}
