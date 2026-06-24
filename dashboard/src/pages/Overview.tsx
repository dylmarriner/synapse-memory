import { useQuery } from '@tanstack/react-query';
import { fetchStats, fetchMetrics } from '../api/nexus';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';

export default function Overview() {
  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: fetchStats, refetchInterval: 15000 });
  const { data: metrics } = useQuery({ queryKey: ['metrics'], queryFn: fetchMetrics, refetchInterval: 15000 });

  const typeData = stats?.by_type?.map((t) => ({ name: t.memory_type, value: t.count })) ?? [];

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Command Overview</div>
          <h2 className="text-3xl m-0 mt-1">Memory Constellation</h2>
        </div>
        <div className="ml-auto flex items-center gap-2 border border-[var(--color-line)] bg-[rgba(102,252,241,.06)] p-[10px_12px] text-[var(--color-cyan)] text-xs uppercase tracking-[.12em]">
          <span className="w-2 h-2 rounded-full bg-[var(--color-green)] shadow-[0_0_18px_var(--color-green)]" />
          connected
        </div>
      </div>

      {/* Stat grid */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Memories', value: stats?.total_memories ?? '...', sig: 'MEM/IDX' },
          { label: 'Agents', value: stats?.total_agents ?? '...', sig: 'NODE/LINK' },
          { label: 'Entities', value: stats?.total_entities ?? '...', sig: 'GRAPH/ENT' },
          { label: 'Conclusions', value: stats?.total_conclusions ?? '...', sig: 'REMEMBER' },
        ].map((s) => (
          <div key={s.label} className="relative overflow-hidden border border-[var(--color-line)] bg-gradient-to-br from-[rgba(102,252,241,.1)] to-[rgba(185,103,255,.035)] p-4 min-h-[100px]">
            <div className="absolute -right-[30px] -top-[30px] w-[90px] h-[90px] border border-[rgba(102,252,241,.25)] rotate-45" />
            <div className="text-[.72rem] text-[var(--color-muted)] uppercase tracking-[.2em]">{s.label}</div>
            <div className="text-4xl mt-3 tabular-nums">{s.value}</div>
            <div className="absolute bottom-3 right-[14px] text-[.7rem] text-[var(--color-dim)]">{s.sig}</div>
          </div>
        ))}
      </div>

      {/* Lower panel */}
      <div className="grid grid-cols-[1.1fr_0.9fr] gap-4 flex-1 min-h-0">
        {/* Type spectrum */}
        <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4 overflow-hidden">
          <h3 className="text-[.82rem] text-[var(--color-cyan)] uppercase tracking-[.16em] m-0 mb-3">Memory Type Spectrum</h3>
          <div className="flex flex-wrap gap-2.5">
            {typeData.map((t) => (
              <span key={t.name} className="border border-[rgba(102,252,241,.22)] bg-[rgba(102,252,241,.045)] p-[9px_12px] text-[.75rem] uppercase tracking-[.1em] text-[var(--color-muted)] hover:text-[var(--color-cyan)] hover:border-[var(--color-cyan)]">
                {t.name} <b>{t.value}</b>
              </span>
            ))}
          </div>

          {/* Memory quality */}
          {metrics && (
            <div className="mt-4 space-y-2 text-xs">
              <div className="flex justify-between text-[var(--color-muted)]">
                <span>Confidence avg</span>
                <span>{(metrics as unknown as { avg_confidence?: number })?.avg_confidence?.toFixed(3) ?? '—'}</span>
              </div>
              <div className="flex justify-between text-[var(--color-muted)]">
                <span>Importance avg</span>
                <span>{(metrics as unknown as { avg_importance?: number })?.avg_importance?.toFixed(3) ?? '—'}</span>
              </div>
            </div>
          )}
        </div>

        {/* Pie chart */}
        <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4">
          <h3 className="text-[.82rem] text-[var(--color-cyan)] uppercase tracking-[.16em] m-0 mb-3">Memory by Type</h3>
          {typeData.length > 0 && (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={typeData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={({ name, percent = 0 }) => `${name} ${(percent * 100).toFixed(0)}%`}>
                  {typeData.map((_, i) => (
                    <Cell key={i} fill={['#66fcf1', '#b967ff', '#ff3cac', '#ffd166', '#63ff9f'][i % 5]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </>
  );
}
