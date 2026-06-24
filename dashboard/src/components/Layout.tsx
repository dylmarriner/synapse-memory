import { useState, useEffect } from 'react';
import { fetchAgents } from '../api/nexus';
import type { AgentSummary } from '../types/nexus';

const TABS = [
  { id: 'overview', label: '◇ Overview' },
  { id: 'vault', label: '▣ Memory Vault' },
  { id: 'agents', label: '⌬ Agent Registry' },
  { id: 'sessions', label: '◷ Sessions' },
  { id: 'recalllab', label: '◬ Recall Lab' },
  { id: 'ops', label: '⚡ Operations' },
  { id: 'console', label: '⌁ Neural Console' },
];

interface LayoutProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
  children: React.ReactNode;
}

export default function Layout({ activeTab, onTabChange, children }: LayoutProps) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);

  useEffect(() => {
    fetchAgents()
      .then((d) => setAgents(d.agents))
      .catch(() => {});
  }, []);

  return (
    <div className="grid h-screen" style={{ gridTemplateColumns: '280px 1fr', gridTemplateRows: '1fr 38px', padding: 18, gap: 16 }}>
      {/* Rail */}
      <aside className="row-span-2 flex flex-col gap-4 p-[18px] border border-[var(--color-line)] bg-gradient-to-b from-[rgba(6,14,31,.9)] to-[rgba(2,5,15,.92)] shadow-[0_0_28px_rgba(102,252,241,.22)]"
        style={{ clipPath: 'polygon(0 18px,18px 0,100% 0,100% calc(100% - 18px),calc(100% - 18px) 100%,0 100%)' }}>
        {/* Brand */}
        <div className="pb-[22px] border-b border-[var(--color-line)] relative">
          <div className="w-[54px] h-[54px] rounded-full border border-[var(--color-cyan)] bg-[radial-gradient(circle,#66fcf1_0_3px,transparent_4px),conic-gradient(from_90deg,transparent,var(--color-cyan),transparent,var(--color-violet),transparent)] shadow-[0_0_24px_rgba(102,252,241,.35)] absolute right-[14px] top-[18px]"
            style={{ animation: 'spin 9s linear infinite' }} />
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.28em]">Unified Memory Core</div>
          <h1 className="m-0 mt-[8px] text-[2.4rem] leading-[.9] tracking-[.08em]" style={{ textShadow: '0 0 18px rgba(102,252,241,.65)' }}>
            NEXUS
          </h1>
          <div className="text-[var(--color-muted)] text-[.82rem] mt-[9px]">semantic · lexical · graph · temporal recall matrix</div>
        </div>

        {/* Nav */}
        <nav className="flex flex-col gap-2">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`text-left uppercase tracking-[.14em] text-[.78rem] flex items-center gap-[11px] p-[13px_14px] border transition-all duration-200
                ${activeTab === tab.id
                  ? 'text-[var(--color-cyan)] border-[rgba(102,252,241,.45)] bg-gradient-to-r from-[rgba(102,252,241,.18)] to-[rgba(185,103,255,.05)] shadow-[inset_3px_0_0_var(--color-cyan),0_0_22px_rgba(102,252,241,.12)]'
                  : 'text-[var(--color-muted)] border-transparent bg-[rgba(102,252,241,.035)] hover:border-[var(--color-line)] hover:text-[var(--color-text)] hover:translate-x-[4px]'
                }`}
              style={{ clipPath: 'polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,0 100%)' }}>
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Agent list sidebar */}
        <div className="border border-[var(--color-line2)] bg-[rgba(3,8,20,.48)] p-3 flex flex-col min-h-0">
          <h3 className="text-[.72rem] text-[var(--color-violet)] uppercase tracking-[.2em] m-0 mb-[10px]">Agent Channels</h3>
          <div className="overflow-auto flex flex-col gap-[6px] flex-1">
            {agents.map((a) => (
              <div key={a.name} className="border border-[rgba(102,252,241,.11)] bg-[rgba(255,255,255,.025)] p-[9px_10px] text-[var(--color-muted)] grid grid-cols-[1fr_auto] gap-2 items-center hover:border-[var(--color-cyan)] hover:text-[var(--color-text)] hover:bg-[rgba(102,252,241,.08)]">
                <span className="truncate text-sm">{a.name}</span>
                <span className="text-[var(--color-cyan)] tabular-nums text-xs">{a.memory_count}</span>
              </div>
            ))}
            {agents.length === 0 && <div className="text-[var(--color-dim)] text-xs">No agents registered</div>}
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex flex-col p-[18px] gap-4 min-w-0 border border-[var(--color-line)] bg-gradient-to-b from-[rgba(6,14,31,.9)] to-[rgba(2,5,15,.92)]"
        style={{ clipPath: 'polygon(0 18px,18px 0,100% 0,100% calc(100% - 18px),calc(100% - 18px) 100%,0 100%)' }}>
        {children}
      </main>

      {/* Ticker */}
      <div id="ticker" className="text-xs text-[var(--color-cyan)] flex items-center gap-2 uppercase tracking-[.12em] border border-[var(--color-line)] bg-[rgba(102,252,241,.06)] p-[8px_12px]">
        <span className="w-[9px] h-[9px] rounded-full bg-[var(--color-green)] shadow-[0_0_18px_var(--color-green)]"
          style={{ animation: 'pulse 1.6s ease-in-out infinite' }} />
        <span>Nexus dashboard · SSE live</span>
      </div>
    </div>
  );
}
