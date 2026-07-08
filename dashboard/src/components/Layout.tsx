import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchAgents, fetchMetrics } from '../api/nexus';
import type { AgentSummary, MetricsResponse } from '../types/nexus';

const TABS = [
  { id: 'hud', label: '◈ HUD', desc: 'system vitals' },
  { id: 'constellation', label: '✦ CONSTELLATION', desc: 'memory links' },
  { id: 'timeline', label: '⏳ TIMELINE', desc: 'learning history' },
  { id: 'observatory', label: '◎ OBSERVATORY', desc: 'live mind state' },
  { id: 'lattice', label: '◬ LATTICE', desc: 'memory records' },
  { id: 'pulse', label: '◉ PULSE', desc: 'live event stream' },
  { id: 'conversations', label: '❝ DIALOG', desc: 'conversations' },
  { id: 'recalllab', label: '◊ RECALL LAB', desc: 'test queries' },
  { id: 'agents', label: '⌬ NODES', desc: 'agent registry' },
  { id: 'sessions', label: '◷ SESSIONS', desc: 'session log' },
  { id: 'ops', label: '⚡ OPS', desc: 'operations' },
  { id: 'console', label: '⌁ CONSOLE', desc: 'direct recall' },
  { id: 'code', label: '⌬ CODE', desc: 'iris gate ladder' },
];

interface LayoutProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
  children: React.ReactNode;
}

function useClock() {
  const [t, setT] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setT(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return t;
}

function formatBytes(n?: number) {
  if (!n) return '0 B';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export default function Layout({ activeTab, onTabChange, children }: LayoutProps) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const { data: metrics } = useQuery<MetricsResponse>({
    queryKey: ['metrics'],
    queryFn: fetchMetrics,
    refetchInterval: 15000,
  });
  const now = useClock();

  useEffect(() => {
    fetchAgents().then((d) => setAgents(d.agents)).catch(() => {});
  }, []);

  const totalMem = metrics?.totals?.memories ?? 0;
  const totalSess = metrics?.totals?.sessions ?? 0;

  return (
    <div className="grid h-screen relative z-10" style={{ gridTemplateColumns: '320px 1fr', gridTemplateRows: 'auto 1fr 36px', padding: 16, gap: 14 }}>
      {/* ═══ SIDEBAR ═══ */}
      <aside className="row-span-3 flex flex-col gap-3 nx-card">
        <div className="relative pb-3 border-b border-[var(--color-line)]">
          {/* Animated orbital ring */}
          <div className="absolute right-2 top-2 w-12 h-12" style={{ animation: 'spin 12s linear infinite' }}>
            <div className="w-full h-full rounded-full border border-dashed border-[var(--color-cyan)] opacity-50" />
            <div className="absolute top-0 left-1/2 w-1.5 h-1.5 rounded-full bg-[var(--color-cyan)] nx-glow -translate-x-1/2" />
          </div>
          <div className="text-[.65rem] text-[var(--color-cyan)] uppercase tracking-[.34em]">Unified Memory Core</div>
          <h1 className="m-0 mt-1 text-[2.2rem] leading-[.85] tracking-[.12em] font-bold nx-glow" style={{ color: 'var(--color-cyan)' }}>
            NEXUS
          </h1>
          <div className="text-[var(--color-muted)] text-[.7rem] mt-1.5 tracking-[.18em] uppercase">
            ◈ synaptic · lexical · graph · temporal
          </div>
        </div>

        {/* Live status pill */}
        <div className="flex items-center gap-2 border border-[var(--color-line)] bg-[rgba(102,252,241,.04)] px-3 py-1.5">
          <span className="nx-pulse" />
          <span className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.18em]">system online</span>
          <span className="ml-auto text-[.62rem] text-[var(--color-muted)] tabular-nums">
            {now.toISOString().slice(11, 19)}
          </span>
        </div>

        {/* Nav */}
        <nav className="flex flex-col gap-1.5">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`text-left uppercase tracking-[.12em] text-[.72rem] flex items-center justify-between gap-2 px-3 py-2 border transition-all duration-200
                ${activeTab === tab.id
                  ? 'text-[var(--color-cyan)] border-[rgba(102,252,241,.55)] bg-gradient-to-r from-[rgba(102,252,241,.2)] to-[rgba(185,103,255,.06)] shadow-[inset_3px_0_0_var(--color-cyan),0_0_18px_rgba(102,252,241,.18)]'
                  : 'text-[var(--color-muted)] border-transparent bg-[rgba(102,252,241,.02)] hover:border-[var(--color-line)] hover:text-[var(--color-text)] hover:translate-x-1'
                }`}>
              <span className="font-semibold">{tab.label}</span>
              <span className="text-[.55rem] opacity-60 lowercase tracking-normal">{tab.desc}</span>
            </button>
          ))}
        </nav>

        {/* Agent list */}
        <div className="border border-[var(--color-line2)] bg-[rgba(3,8,20,.5)] p-2.5 flex flex-col min-h-0 flex-1">
          <h3 className="text-[.62rem] text-[var(--color-violet)] uppercase tracking-[.22em] m-0 mb-2 flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-violet)] nx-glow" style={{ color: 'var(--color-violet)' }} />
            NODES · {agents.length}
          </h3>
          <div className="overflow-auto flex flex-col gap-1 flex-1">
            {agents.map((a) => (
              <div key={a.name} className="border border-[rgba(102,252,241,.1)] bg-[rgba(255,255,255,.02)] px-2 py-1.5 flex items-center gap-2 hover:border-[var(--color-cyan)] hover:bg-[rgba(102,252,241,.08)] transition-colors">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-green)]" style={{ boxShadow: '0 0 6px var(--color-green)' }} />
                <span className="text-[var(--color-text)] text-[.78rem] flex-1 truncate">{a.name}</span>
                <span className="text-[var(--color-cyan)] tabular-nums text-[.7rem]">{a.memory_count}</span>
              </div>
            ))}
            {agents.length === 0 && <div className="text-[var(--color-dim)] text-[.7rem]">no nodes</div>}
          </div>
        </div>

        {/* Footer mini-stats */}
        <div className="grid grid-cols-2 gap-1.5 text-[.62rem]">
          <div className="border border-[var(--color-line)] bg-[rgba(102,252,241,.04)] px-2 py-1.5">
            <div className="text-[var(--color-muted)] uppercase tracking-[.16em]">memory</div>
            <div className="text-[var(--color-cyan)] tabular-nums text-base">{totalMem.toLocaleString()}</div>
          </div>
          <div className="border border-[var(--color-line)] bg-[rgba(102,252,241,.04)] px-2 py-1.5">
            <div className="text-[var(--color-muted)] uppercase tracking-[.16em]">sessions</div>
            <div className="text-[var(--color-cyan)] tabular-nums text-base">{totalSess.toLocaleString()}</div>
          </div>
        </div>
      </aside>

      {/* ═══ TOP STATUS BAR ═══ */}
      <div className="grid grid-cols-6 gap-2">
        {[
          { label: 'memories', value: metrics?.totals?.memories, color: 'cyan' },
          { label: 'agents', value: metrics?.totals?.agents, color: 'violet' },
          { label: 'entities', value: metrics?.totals?.entities, color: 'magenta' },
          { label: 'sessions', value: metrics?.totals?.sessions, color: 'amber' },
          { label: '24h events', value: Object.values(metrics?.last_24h ?? {}).reduce((a, b) => a + b, 0), color: 'green' },
          { label: 'obelisk events', value: metrics?.obelisk?.total_events, color: 'red' },
        ].map((s) => (
          <div key={s.label} className="nx-card relative overflow-hidden">
            <div className="absolute -right-4 -top-4 w-10 h-10 border border-[rgba(102,252,241,.18)] rotate-45" />
            <div className="text-[.6rem] text-[var(--color-muted)] uppercase tracking-[.18em]">{s.label}</div>
            <div className="text-2xl tabular-nums mt-1 nx-glow" style={{ color: `var(--color-${s.color})` }}>
              {typeof s.value === 'number' ? s.value.toLocaleString() : '—'}
            </div>
          </div>
        ))}
      </div>

      {/* ═══ MAIN CONTENT ═══ */}
      <main className="nx-card overflow-auto relative">
        {children}
      </main>

      {/* ═══ BOTTOM TICKER ═══ */}
      <div className="col-span-1 text-[.65rem] text-[var(--color-cyan)] flex items-center gap-3 uppercase tracking-[.18em] border border-[var(--color-line)] bg-[rgba(102,252,241,.04)] px-3">
        <span className="nx-pulse" />
        <span>nexus://</span>
        <span className="text-[var(--color-muted)]">live</span>
        <span className="text-[var(--color-dim)]">·</span>
        <span className="text-[var(--color-muted)] tabular-nums">{now.toISOString().slice(0, 10)}</span>
        <span className="text-[var(--color-muted)] tabular-nums ml-auto">{now.toISOString().slice(11, 19)} UTC</span>
        <span className="text-[var(--color-dim)]">·</span>
        <span className="text-[var(--color-muted)]">{formatBytes(metrics?.obelisk?.tokens_saved_estimate)} tokens saved</span>
      </div>
    </div>
  );
}
