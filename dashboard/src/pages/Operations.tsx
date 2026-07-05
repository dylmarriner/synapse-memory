import { useQuery } from '@tanstack/react-query';
import { fetchMetrics, fetchRtkSummary } from '../api/nexus';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

export default function Operations() {
  const { data: metrics } = useQuery({ queryKey: ['metrics'], queryFn: fetchMetrics, refetchInterval: 15000 });
  const { data: rtk } = useQuery({ queryKey: ['rtk-summary'], queryFn: fetchRtkSummary, refetchInterval: 15000 });

  const rtks = metrics?.rtk;
  const totals = metrics?.totals;

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Operations</div>
          <h2 className="text-3xl m-0 mt-1">RTK · Sessions · Telemetry</h2>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Sessions', value: totals?.sessions ?? '…', sig: 'RAW/CTX' },
          { label: 'Messages', value: totals?.messages ?? '…', sig: 'EVENT/LOG' },
          { label: 'RTK Saved', value: rtks?.tokens_saved_estimate ?? '…', sig: 'TOKENS' },
          { label: 'RTK Failures', value: rtks?.failed_24h ?? '…', sig: '24H' },
        ].map((s) => (
          <div key={s.label} className="border border-[var(--color-line)] bg-gradient-to-br from-[rgba(102,252,241,.1)] to-[rgba(185,103,255,.035)] p-4 min-h-[80px] relative overflow-hidden">
            <div className="text-[.72rem] text-[var(--color-muted)] uppercase tracking-[.2em]">{s.label}</div>
            <div className="text-3xl mt-2 tabular-nums">{s.value}</div>
            <div className="absolute bottom-3 right-[14px] text-[.7rem] text-[var(--color-dim)]">{s.sig}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 flex-1 min-h-0 overflow-auto">
        {/* RTK by agent */}
        <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4">
          <h3 className="text-[.82rem] text-[var(--color-cyan)] uppercase tracking-[.16em] m-0 mb-3">RTK By Agent</h3>
          {rtk?.by_agent?.length ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={rtk.by_agent}>
                <XAxis dataKey="agent_id" tick={{ fontSize: 10, fill: '#6e8c9b' }} />
                <YAxis tick={{ fontSize: 10, fill: '#6e8c9b' }} />
                <Tooltip />
                <Bar dataKey="count" fill="#66fcf1" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-xs text-[var(--color-dim)]">No RTK telemetry yet.</div>
          )}
          <div className="mt-2 space-y-1 text-xs text-[var(--color-muted)]">
            {rtk?.by_agent?.slice(0, 5).map((a) => (
              <div key={a.agent_id}>{a.agent_id}: {a.tokens_saved_estimate} tokens · {a.count} cmds · {a.failures} failures</div>
            ))}
          </div>
        </div>

        {/* Recent events */}
        <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4 overflow-auto">
          <h3 className="text-[.82rem] text-[var(--color-cyan)] uppercase tracking-[.16em] m-0 mb-3">Recent Events</h3>
          <div className="space-y-1 text-xs font-mono">
            {metrics?.recent_events?.slice(0, 15).map((e) => (
              <div key={e.id} className="text-[var(--color-muted)]">
                {e.created_at ? new Date(e.created_at).toLocaleTimeString() : ''} [{e.action}] {e.actor || ''}
              </div>
            ))}
            {(!metrics?.recent_events || metrics.recent_events.length === 0) && (
              <div className="text-[var(--color-dim)]">No recent events.</div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
