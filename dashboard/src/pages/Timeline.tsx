import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchMemories, fetchAgents } from '../api/nexus';
import type { BrowseMemory, AgentSummary } from '../types/nexus';

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

function fmtRel(iso: string | null): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  if (diff < 0) return 'in the future';
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  if (s < 86400 * 365) return `${Math.floor(s / 86400 / 30)}mo ago`;
  return `${Math.floor(s / 86400 / 365)}y ago`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  });
}

export default function Timeline() {
  const { data: agentsData } = useQuery({ queryKey: ['agents'], queryFn: fetchAgents });
  const { data, isLoading } = useQuery({
    queryKey: ['timeline-memories'],
    queryFn: () => fetchMemories({ limit: 200 }),
    refetchInterval: 30000,
  });
  const [filterAgent, setFilterAgent] = useState<string>('');
  const [filterType, setFilterType] = useState<string>('');
  const [selected, setSelected] = useState<BrowseMemory | null>(null);

  const memories = useMemo(() => (data?.memories ?? []).filter((m) => {
    if (filterAgent && m.agent_name !== filterAgent) return false;
    if (filterType && m.memory_type !== filterType) return false;
    return true;
  }), [data, filterAgent, filterType]);

  // Group by day
  const grouped = useMemo(() => {
    const m = new Map<string, BrowseMemory[]>();
    for (const mem of memories) {
      if (!mem.created_at) continue;
      const day = mem.created_at.slice(0, 10);
      if (!m.has(day)) m.set(day, []);
      m.get(day)!.push(mem);
    }
    return Array.from(m.entries()).sort((a, b) => b[0].localeCompare(a[0]));
  }, [memories]);

  // Stats per day for sparkline
  const dayCounts = useMemo(() => grouped.map(([d, list]) => ({ d, n: list.length })), [grouped]);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Title */}
      <div className="flex items-end gap-3">
        <div>
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.34em]">Chronicle</div>
          <h2 className="text-3xl m-0 mt-1 nx-glow" style={{ color: 'var(--color-magenta)' }}>LEARNING TIMELINE</h2>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <select value={filterAgent} onChange={(e) => setFilterAgent(e.target.value)}
            className="bg-[rgba(102,252,241,.04)] border border-[var(--color-line)] text-[.7rem] uppercase tracking-[.14em] px-2 py-1.5 text-[var(--color-text)] outline-none">
            <option value="">all agents</option>
            {(agentsData?.agents ?? []).map((a: AgentSummary) => <option key={a.name} value={a.name}>{a.name}</option>)}
          </select>
          <select value={filterType} onChange={(e) => setFilterType(e.target.value)}
            className="bg-[rgba(102,252,241,.04)] border border-[var(--color-line)] text-[.7rem] uppercase tracking-[.14em] px-2 py-1.5 text-[var(--color-text)] outline-none">
            <option value="">all types</option>
            {Object.keys(TYPE_COLORS).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>

      {/* Sparkline of activity per day */}
      <div className="nx-card">
        <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.22em] mb-2">Activity Pulse · {dayCounts.length} days · {memories.length} memories</div>
        <div className="flex items-end gap-[2px] h-12">
          {dayCounts.map(({ d, n }) => {
            const max = Math.max(...dayCounts.map((x) => x.n), 1);
            return (
              <div key={d} className="flex-1 group relative">
                <div className="h-full bg-[rgba(102,252,241,.04)] border border-[var(--color-line)] relative" style={{ height: `${(n / max) * 100}%`, minHeight: 2 }}>
                  <div className="absolute inset-0 bg-gradient-to-t from-[var(--color-cyan)] to-[var(--color-violet)] opacity-70 group-hover:opacity-100 transition-opacity" style={{ boxShadow: n > max * 0.7 ? '0 0 8px var(--color-cyan)' : 'none' }} />
                </div>
                <div className="absolute -top-6 left-1/2 -translate-x-1/2 text-[.55rem] text-[var(--color-cyan)] opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">{d} · {n}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Timeline */}
      <div className="grid grid-cols-[1fr_360px] gap-3 flex-1 min-h-0">
        <div className="nx-card overflow-auto pr-2">
          {isLoading && <div className="text-center py-8 text-[var(--color-dim)]">Loading chronicle…</div>}
          {!isLoading && grouped.length === 0 && (
            <div className="text-center py-8 text-[var(--color-dim)]">No memories match the current filters.</div>
          )}
          {grouped.map(([day, list]) => (
            <div key={day} className="mb-6">
              <div className="flex items-center gap-2 mb-2 sticky top-0 bg-[rgba(2,4,12,.85)] backdrop-blur-sm py-1.5 z-10 -mx-1 px-1">
                <span className="text-[.95rem] text-[var(--color-cyan)] font-bold tracking-[.16em] tabular-nums">{day}</span>
                <span className="text-[.6rem] text-[var(--color-muted)] uppercase tracking-[.18em]">· {list.length} memories</span>
                <div className="flex-1 h-px bg-gradient-to-r from-[var(--color-cyan)] to-transparent" />
              </div>
              <div className="relative pl-6">
                {/* Vertical line */}
                <div className="absolute left-2 top-0 bottom-0 w-px bg-gradient-to-b from-[var(--color-cyan)] via-[var(--color-violet)] to-transparent" />
                {list.map((m) => {
                  const color = TYPE_COLORS[m.memory_type] ?? '#66fcf1';
                  const glyph = TYPE_GLYPHS[m.memory_type] ?? '◆';
                  const isSel = selected?.id === m.id;
                  return (
                    <div key={m.id} className="relative mb-2 group">
                      {/* node dot */}
                      <div className="absolute -left-[18px] top-2 w-2.5 h-2.5 rounded-full" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
                      <div
                        onClick={() => setSelected(isSel ? null : m)}
                        className={`border p-2 transition-all cursor-pointer ${isSel ? 'border-[var(--color-cyan)] bg-[rgba(102,252,241,.08)]' : 'border-[var(--color-line)] bg-[rgba(255,255,255,.02)] hover:border-[var(--color-cyan)] hover:bg-[rgba(102,252,241,.04)]'}`}
                      >
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className="text-[1rem]" style={{ color }}>{glyph}</span>
                          <span className="nx-tag" style={{ borderColor: color + '88', color }}>{m.memory_type}</span>
                          <span className="text-[.7rem] text-[var(--color-violet)]">{m.agent_name ?? '—'}</span>
                          {m.importance > 0.7 && <span className="text-[.55rem] text-[var(--color-amber)] uppercase">★ important</span>}
                          {m.confirmed_count > 0 && <span className="text-[.55rem] text-[var(--color-green)]">✓{m.confirmed_count}</span>}
                          {m.contradicted_count > 0 && <span className="text-[.55rem] text-[var(--color-red)]">⚠{m.contradicted_count}</span>}
                          <span className="ml-auto text-[.6rem] text-[var(--color-dim)] tabular-nums">{fmtRel(m.created_at)}</span>
                        </div>
                        <div className="text-[var(--color-text)] text-[.8rem] leading-relaxed">{m.content}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Inspector */}
        <div className="nx-card flex flex-col overflow-hidden">
          {!selected && (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-6">
              <div className="text-3xl mb-3" style={{ color: 'var(--color-magenta)' }}>⏳</div>
              <div className="text-[var(--color-text)] text-base mb-1">Inspect a memory</div>
              <div className="text-[.8rem] text-[var(--color-dim)]">Click any memory on the timeline to see full provenance, importance, and trust signals.</div>
            </div>
          )}
          {selected && (
            <div className="flex-1 overflow-auto space-y-3 text-sm">
              <div className="flex items-center gap-2 pb-2 border-b border-[var(--color-line)]">
                <span className="text-2xl" style={{ color: TYPE_COLORS[selected.memory_type] }}>{TYPE_GLYPHS[selected.memory_type]}</span>
                <span className="uppercase text-xs tracking-[.2em] font-bold" style={{ color: TYPE_COLORS[selected.memory_type] }}>{selected.memory_type}</span>
                <button onClick={() => setSelected(null)} className="ml-auto text-[var(--color-dim)] hover:text-[var(--color-text)] text-lg">×</button>
              </div>
              <div className="text-[var(--color-text)] text-[.85rem] leading-relaxed">{selected.content}</div>

              <div className="border border-[var(--color-line)] bg-[rgba(102,252,241,.04)] p-2.5 space-y-1.5 text-[.72rem]">
                <div className="text-[.6rem] text-[var(--color-cyan)] uppercase tracking-[.2em] mb-1">Provenance</div>
                <Row label="agent" value={selected.agent_name ?? '—'} />
                <Row label="id" value={selected.id} mono />
                <Row label="created" value={fmtDate(selected.created_at)} />
                <Row label="relative" value={fmtRel(selected.created_at)} />
                <Row label="importance" value={`${(selected.importance * 100).toFixed(0)}%`} bar={selected.importance} />
                <Row label="confidence" value={selected.confidence?.toFixed(2) ?? '—'} bar={selected.confidence} />
                <Row label="accessed" value={`${selected.access_count ?? 0}x`} />
                <Row label="confirmed" value={`${selected.confirmed_count ?? 0}x`} color="green" />
                <Row label="contradicted" value={`${selected.contradicted_count ?? 0}x`} color="red" />
              </div>

              {selected.metadata && Object.keys(selected.metadata).length > 0 && (
                <div className="border-t border-[var(--color-line)] pt-2">
                  <div className="text-[.6rem] text-[var(--color-cyan)] uppercase tracking-[.2em] mb-1.5">Metadata</div>
                  <div className="space-y-1 text-[.68rem]">
                    {Object.entries(selected.metadata).slice(0, 20).map(([k, v]) => (
                      <div key={k} className="flex gap-2 border-b border-[rgba(102,252,241,.05)] pb-0.5">
                        <span className="text-[var(--color-dim)] min-w-[88px]">{k}</span>
                        <span className="break-words flex-1">{typeof v === 'object' ? JSON.stringify(v).slice(0, 100) : String(v ?? '—')}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, color, mono, bar }: { label: string; value: string; color?: string; mono?: boolean; bar?: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[var(--color-muted)] w-20 shrink-0">{label}</span>
      {bar != null ? (
        <div className="flex-1 flex items-center gap-2">
          <div className="flex-1 h-1.5 bg-[rgba(102,252,241,.05)] border border-[var(--color-line)] relative">
            <div className="h-full bg-[var(--color-cyan)]" style={{ width: `${bar * 100}%`, boxShadow: '0 0 4px var(--color-cyan)' }} />
          </div>
          <span className="text-[var(--color-cyan)] tabular-nums w-10 text-right text-[.68rem]">{value}</span>
        </div>
      ) : (
        <span className={`${mono ? 'nx-mono' : ''} ${color ? 'text-[var(--color-' + color + ')]' : 'text-[var(--color-text)]'} break-all flex-1 text-[.68rem]`}>{value}</span>
      )}
    </div>
  );
}
