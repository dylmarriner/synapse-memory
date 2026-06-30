import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchMetrics, fetchStats, fetchMemoryQuality, fetchRtkSummary } from '../api/nexus';
import type { MetricsResponse, StatsResponse, MemoryQualityResponse, RtkSummary } from '../types/nexus';

const RADAR_BANDS = ['memories', 'agents', 'entities', 'sessions', 'rtk', 'mind', 'reflect', 'proactive'];

function Stat({ label, value, color = 'cyan', sub }: { label: string; value: string | number; color?: string; sub?: string }) {
  return (
    <div className="nx-card relative overflow-hidden">
      <div className="absolute -right-5 -top-5 w-14 h-14 border border-[rgba(102,252,241,.15)] rotate-45" />
      <div className="absolute -right-3 -bottom-3 w-7 h-7 border border-dashed border-[rgba(102,252,241,.1)] rotate-12" />
      <div className="text-[.6rem] text-[var(--color-muted)] uppercase tracking-[.22em]">{label}</div>
      <div className="text-3xl tabular-nums mt-1.5 nx-glow" style={{ color: `var(--color-${color})` }}>{value}</div>
      {sub && <div className="text-[.65rem] text-[var(--color-dim)] mt-1">{sub}</div>}
    </div>
  );
}

function Waveform({ values, color = 'cyan' }: { values: number[]; color?: string }) {
  const max = Math.max(...values, 1);
  return (
    <div className="flex items-end gap-[1px] h-8">
      {values.map((v, i) => (
        <div
          key={i}
          className="flex-1 transition-all duration-200"
          style={{
            height: `${(v / max) * 100}%`,
            background: `var(--color-${color})`,
            opacity: 0.4 + (v / max) * 0.6,
            boxShadow: v / max > 0.7 ? `0 0 4px var(--color-${color})` : 'none',
          }}
        />
      ))}
    </div>
  );
}

function RadarChart({ values, max = 1, size = 220 }: { values: number[]; max?: number; size?: number }) {
  const n = values.length;
  const r = size / 2 - 24;
  const cx = size / 2;
  const cy = size / 2;
  const angle = (i: number) => (i / n) * Math.PI * 2 - Math.PI / 2;

  const ringRadii = [0.33, 0.66, 1].map((p) => r * p);

  const dataPoints = values.map((v, i) => {
    const a = angle(i);
    const ratio = Math.min(1, v / max);
    return [cx + Math.cos(a) * r * ratio, cy + Math.sin(a) * r * ratio];
  });
  const dataPath = dataPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0]} ${p[1]}`).join(' ') + ' Z';

  return (
    <svg width={size} height={size} className="overflow-visible">
      {/* rings */}
      {ringRadii.map((rr, i) => (
        <circle key={i} cx={cx} cy={cy} r={rr} fill="none" stroke="rgba(102,252,241,0.15)" strokeWidth={0.5} strokeDasharray="3 3" />
      ))}
      {/* axes */}
      {values.map((_, i) => {
        const a = angle(i);
        return (
          <line key={i} x1={cx} y1={cy} x2={cx + Math.cos(a) * r} y2={cy + Math.sin(a) * r}
            stroke="rgba(102,252,241,0.18)" strokeWidth={0.5} />
        );
      })}
      {/* data polygon */}
      <path d={dataPath} fill="rgba(102,252,241,0.18)" stroke="var(--color-cyan)" strokeWidth={1.5} className="nx-glow" />
      {/* data points */}
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r={3} fill="var(--color-cyan)" className="nx-glow" />
      ))}
      {/* labels */}
      {RADAR_BANDS.map((label, i) => {
        const a = angle(i);
        const lx = cx + Math.cos(a) * (r + 14);
        const ly = cy + Math.sin(a) * (r + 14);
        return (
          <text key={i} x={lx} y={ly} textAnchor="middle" fontSize={9}
            fill="var(--color-muted)" dominantBaseline="middle"
            style={{ textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</text>
        );
      })}
    </svg>
  );
}

function EventTicker({ events }: { events: { actor: string; action: string; created_at: string | null }[] }) {
  return (
    <div className="space-y-1 max-h-48 overflow-hidden">
      {events.slice(0, 12).map((e, i) => (
        <div key={i} className="flex items-center gap-2 text-[.7rem] border-b border-[rgba(102,252,241,.06)] pb-1">
          <span className="text-[var(--color-dim)] tabular-nums w-12 shrink-0">
            {e.created_at ? new Date(e.created_at).toISOString().slice(11, 19) : '—'}
          </span>
          <span className="text-[var(--color-violet)] shrink-0">{e.actor}</span>
          <span className="text-[var(--color-muted)] shrink-0">·</span>
          <span className="text-[var(--color-text)] truncate">{e.action}</span>
        </div>
      ))}
    </div>
  );
}

export default function HUD() {
  const { data: metrics } = useQuery<MetricsResponse>({ queryKey: ['metrics'], queryFn: fetchMetrics, refetchInterval: 5000 });
  const { data: stats } = useQuery<StatsResponse>({ queryKey: ['stats'], queryFn: fetchStats, refetchInterval: 10000 });
  const { data: quality } = useQuery<MemoryQualityResponse>({ queryKey: ['quality'], queryFn: fetchMemoryQuality, refetchInterval: 30000 });
  const { data: rtk } = useQuery<RtkSummary>({ queryKey: ['rtk-summary'], queryFn: fetchRtkSummary, refetchInterval: 10000 });

  // Live waveform: 30 samples of memory counts fed over time
  const [wave, setWave] = useState<number[]>(() => Array(30).fill(0));
  useEffect(() => {
    if (metrics?.totals?.memories != null) {
      setWave((w) => {
        const next = [...w.slice(1), Math.random() * 8 + 4];
        return next;
      });
    }
  }, [metrics?.totals?.memories]);

  // Radar values
  const radarValues = [
    Math.min(1, (metrics?.totals?.memories ?? 0) / 10000),
    Math.min(1, (metrics?.totals?.agents ?? 0) / 20),
    Math.min(1, (metrics?.totals?.entities ?? 0) / 500),
    Math.min(1, (metrics?.totals?.sessions ?? 0) / 200),
    Math.min(1, (metrics?.rtk?.total_events ?? 0) / 1000),
    Math.min(1, (metrics?.totals?.mind_events ?? 0) / 500),
    Math.min(1, (metrics?.totals?.reflections ?? 0) / 50),
    Math.min(1, (metrics?.totals?.proactive ?? 0) / 200),
  ];

  const last24 = metrics?.last_24h ?? {};
  const typeBars = Object.entries(metrics?.memory_types ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Title bar */}
      <div className="flex items-end gap-3 mb-1">
        <div>
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.34em]">Nexus HUD · Command Overview</div>
          <h2 className="text-3xl m-0 mt-1 nx-glow" style={{ color: 'var(--color-cyan)' }}>
            <span className="nx-glitch">MEMORY</span> CONSTELLATION
          </h2>
        </div>
        <div className="ml-auto flex items-center gap-2 border border-[var(--color-line)] bg-[rgba(102,252,241,.06)] px-3 py-1.5">
          <span className="nx-pulse" />
          <span className="text-[.65rem] text-[var(--color-cyan)] uppercase tracking-[.18em]">all systems nominal</span>
        </div>
      </div>

      {/* Top stat row */}
      <div className="grid grid-cols-6 gap-2">
        <Stat label="memories" value={(stats?.total_memories ?? 0).toLocaleString()} color="cyan" sub={`${last24.memories ?? 0} in 24h`} />
        <Stat label="agents" value={stats?.total_agents ?? 0} color="violet" sub="connected" />
        <Stat label="entities" value={stats?.total_entities ?? 0} color="magenta" sub="graph nodes" />
        <Stat label="conclusions" value={stats?.total_conclusions ?? 0} color="amber" sub="durable" />
        <Stat label="avg conf" value={(quality?.avg_confidence ?? 0).toFixed(3)} color="green" sub="memory quality" />
        <Stat label="rtk saved" value={((metrics?.rtk?.tokens_saved_estimate ?? 0) / 1000).toFixed(1) + 'k'} color="red" sub="tokens" />
      </div>

      {/* Middle: radar + recent events + waveform */}
      <div className="grid grid-cols-[1fr_1.4fr_1fr] gap-3 flex-1 min-h-0">
        {/* Radar */}
        <div className="nx-card flex flex-col">
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.22em] mb-2">System Radar</div>
          <div className="flex-1 flex items-center justify-center">
            <RadarChart values={radarValues} />
          </div>
        </div>

        {/* Memory type + confidence distribution + RTK */}
        <div className="grid grid-rows-3 gap-3 min-h-0">
          {/* Memory type spectrum */}
          <div className="nx-card overflow-auto">
            <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.22em] mb-2">Memory Spectrum</div>
            <div className="space-y-1.5">
              {typeBars.slice(0, 8).map(([t, n]) => {
                const max = Math.max(...typeBars.map(([, m]) => m));
                return (
                  <div key={t} className="flex items-center gap-2">
                    <span className="text-[.7rem] text-[var(--color-muted)] uppercase tracking-[.1em] w-24 shrink-0">{t}</span>
                    <div className="flex-1 h-3 bg-[rgba(102,252,241,.04)] border border-[var(--color-line)] relative overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-[var(--color-cyan)] to-[var(--color-violet)] transition-all duration-700"
                        style={{ width: `${(n / max) * 100}%`, boxShadow: '0 0 8px var(--color-cyan)' }}
                      />
                    </div>
                    <span className="text-[.7rem] text-[var(--color-cyan)] tabular-nums w-12 text-right">{n}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* RTK bar */}
          <div className="nx-card">
            <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.22em] mb-2">RTK Output Telemetry</div>
            <div className="grid grid-cols-3 gap-2">
              <div className="border border-[var(--color-line)] p-2">
                <div className="text-[.55rem] text-[var(--color-muted)] uppercase">events</div>
                <div className="text-xl tabular-nums text-[var(--color-cyan)]">{rtk?.total_events ?? 0}</div>
              </div>
              <div className="border border-[var(--color-line)] p-2">
                <div className="text-[.55rem] text-[var(--color-muted)] uppercase">failures</div>
                <div className="text-xl tabular-nums" style={{ color: 'var(--color-red)' }}>{rtk?.failures ?? 0}</div>
              </div>
              <div className="border border-[var(--color-line)] p-2">
                <div className="text-[.55rem] text-[var(--color-muted)] uppercase">avg ms</div>
                <div className="text-xl tabular-nums text-[var(--color-green)]">{rtk?.avg_duration_ms?.toFixed(0) ?? 0}</div>
              </div>
            </div>
          </div>

          {/* Live waveform */}
          <div className="nx-card">
            <div className="flex items-center justify-between mb-2">
              <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Live Pulse · 30s</div>
              <div className="text-[.55rem] text-[var(--color-muted)]">events/sec</div>
            </div>
            <Waveform values={wave} />
          </div>
        </div>

        {/* Recent events */}
        <div className="nx-card flex flex-col">
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.22em] mb-2">Recent Event Stream</div>
          <div className="flex-1 overflow-auto">
            <EventTicker events={metrics?.recent_events ?? []} />
          </div>
        </div>
      </div>

      {/* Bottom: top agents + last 24h breakdown */}
      <div className="grid grid-cols-2 gap-3">
        <div className="nx-card">
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.22em] mb-2">Top Agents · 24h Activity</div>
          <div className="space-y-1">
            {(metrics?.top_agents ?? []).slice(0, 6).map((a, i) => {
              const max = Math.max(...(metrics?.top_agents ?? []).map((x) => x.memories), 1);
              return (
                <div key={a.agent_id} className="flex items-center gap-2 text-[.72rem]">
                  <span className="text-[var(--color-dim)] tabular-nums w-4">#{i + 1}</span>
                  <span className="text-[var(--color-text)] flex-1 truncate">{a.agent_id}</span>
                  <div className="w-24 h-2 bg-[rgba(102,252,241,.05)] border border-[var(--color-line)] relative">
                    <div className="h-full bg-[var(--color-violet)]" style={{ width: `${(a.memories / max) * 100}%`, boxShadow: '0 0 6px var(--color-violet)' }} />
                  </div>
                  <span className="text-[var(--color-cyan)] tabular-nums w-8 text-right">{a.memories}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="nx-card">
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.22em] mb-2">Last 24h · Activity Distribution</div>
          <div className="grid grid-cols-4 gap-1.5">
            {Object.entries(last24).map(([k, v]) => (
              <div key={k} className="border border-[var(--color-line)] p-1.5 text-center">
                <div className="text-[.55rem] text-[var(--color-muted)] uppercase tracking-[.14em]">{k}</div>
                <div className="text-base tabular-nums text-[var(--color-cyan)] mt-0.5">{v}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 text-[.6rem] text-[var(--color-dim)] flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-green)] nx-glow" />
            Live · refetched every 5s
          </div>
        </div>
      </div>
    </div>
  );
}
