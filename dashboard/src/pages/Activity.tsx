import { useQuery } from '@tanstack/react-query';
import { fetchMindLearningEvents, fetchMindProactiveLog } from '../api/nexus';

const KIND_COLOR: Record<string, string> = {
  interaction_learning: 'var(--color-cyan)',
  pattern: 'var(--color-violet)',
  capability: 'var(--color-green)',
  limitation: 'var(--color-red)',
  opinion_formed: 'var(--color-magenta)',
  identity_update: 'var(--color-amber)',
};

function timeAgo(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso).getTime();
  const s = Math.floor((Date.now() - d) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function Activity() {
  const { data: learning, isLoading: lLoading, error: lError } = useQuery({
    queryKey: ['mind-learning'],
    queryFn: () => fetchMindLearningEvents('default', 100),
    refetchInterval: 10000,
  });
  const { data: proactive, isLoading: pLoading } = useQuery({
    queryKey: ['mind-proactive'],
    queryFn: () => fetchMindProactiveLog('default', 100),
    refetchInterval: 10000,
  });

  const events = learning?.events ?? [];
  const items = proactive?.items ?? [];

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Mind Activity</div>
          <h2 className="text-3xl m-0 mt-1">Thought Stream · Proactive Log</h2>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 flex-1 min-h-0">
        {/* Learning events = the thought stream */}
        <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4 overflow-auto flex flex-col min-h-0">
          <div className="text-[var(--color-cyan)] uppercase text-xs tracking-[.16em] mb-2 shrink-0">
            Thought Stream — every learning the mind extracted ({events.length})
          </div>
          {lLoading && <div className="text-[var(--color-dim)] text-sm">Loading…</div>}
          {lError && <div className="text-[var(--color-red)] text-sm">Failed: {String(lError)}</div>}
          {!lLoading && events.length === 0 && (
            <div className="text-[var(--color-dim)] text-sm">No learning events yet — the mind records these as it thinks.</div>
          )}
          <div className="space-y-2">
            {events.map((e, i) => (
              <div key={i} className="border-b border-[rgba(102,252,241,.08)] pb-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className="uppercase tracking-[.1em] text-[.6rem]" style={{ color: KIND_COLOR[e.kind] || 'var(--color-muted)' }}>
                    {e.kind}
                  </span>
                  {e.source && <span className="text-[var(--color-dim)]">· {e.source}</span>}
                  <span className="ml-auto text-[var(--color-dim)]">{timeAgo(e.created_at)}</span>
                </div>
                <div className="text-[var(--color-text)] mt-1">{e.description}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Proactive log */}
        <div className="border border-[rgba(185,103,255,.25)] bg-[var(--color-panel)] p-4 overflow-auto flex flex-col min-h-0">
          <div className="text-[var(--color-violet)] uppercase text-xs tracking-[.16em] mb-2 shrink-0">
            Proactive Log — what the mind volunteered ({items.length})
          </div>
          {pLoading && <div className="text-[var(--color-dim)] text-sm">Loading…</div>}
          {!pLoading && items.length === 0 && (
            <div className="text-[var(--color-dim)] text-sm">No proactive items surfaced yet.</div>
          )}
          <div className="space-y-2">
            {items.map((it, i) => (
              <div key={i} className="border-b border-[rgba(185,103,255,.12)] pb-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-[var(--color-violet)] uppercase tracking-[.1em] text-[.6rem]">{it.item_type}</span>
                  <span className="text-[var(--color-dim)]">→ {it.agent_id}</span>
                  <span className="ml-auto text-[var(--color-muted)]">rel {it.relevance.toFixed(2)}</span>
                </div>
                <div className="text-[var(--color-text)] mt-1">{it.content}</div>
                <div className="text-[var(--color-dim)] mt-0.5">{timeAgo(it.created_at)}{it.used ? ' · used' : ''}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
