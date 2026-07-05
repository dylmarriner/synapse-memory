import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchAgents, fetchAgentCard } from '../api/nexus';

export default function Agents() {
  const [selected, setSelected] = useState<string | null>(null);
  const { data: agents, isLoading: agentsLoading, error: agentsError } = useQuery({ queryKey: ['agents'], queryFn: fetchAgents, refetchInterval: 15000 });
  const { data: card, isLoading: cardLoading, error: cardError } = useQuery({
    queryKey: ['agent-card', selected],
    queryFn: () => fetchAgentCard(selected!),
    enabled: !!selected,
  });

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Agent Registry</div>
          <h2 className="text-3xl m-0 mt-1">Channel Topology</h2>
        </div>
      </div>

      <div className="grid grid-cols-[1fr_1fr] gap-4 flex-1 min-h-0">
        {/* Agent cards */}
        <div className="overflow-auto space-y-2">
          {agentsLoading && <div className="text-[var(--color-dim)] text-sm">Loading agent channels…</div>}
          {agentsError && <div className="text-[var(--color-red)] text-sm">Failed to load agents: {String(agentsError)}</div>}
          {agents?.agents?.map((a) => (
            <button
              key={a.name}
              type="button"
              className={`w-full text-left border p-3 cursor-pointer ${selected === a.name ? 'border-[var(--color-cyan)] bg-[rgba(102,252,241,.08)]' : 'border-[rgba(102,252,241,.11)] bg-[rgba(255,255,255,.025)]'} hover:border-[var(--color-cyan)]`}
              onClick={() => setSelected(a.name)}
              aria-pressed={selected === a.name}>
              <h4 className="m-0 text-sm">{a.name}</h4>
              <div className="text-xs text-[var(--color-dim)] flex gap-2 mt-1">
                <span>mem {a.memory_count}</span>
                <span>ent {a.entity_count}</span>
                <span>rules {a.conclusion_count}</span>
                <span>sessions {a.session_count}</span>
                <span className="ml-auto">{a.last_active ? new Date(a.last_active).toLocaleDateString() : ''}</span>
              </div>
            </button>
          ))}
        </div>

        {/* Detail panel */}
        <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4 overflow-auto">
          {!selected && <div className="text-[var(--color-dim)] text-sm">Select an agent channel to inspect.</div>}
          {cardLoading && <div className="text-[var(--color-dim)] text-sm">Loading agent card…</div>}
          {cardError && <div className="text-[var(--color-red)] text-sm">Failed to load agent card: {String(cardError)}</div>}
          {card && (
            <div className="space-y-3 text-sm leading-relaxed">
              <div className="flex items-center gap-2">
                <span className="text-[var(--color-cyan)] uppercase text-xs tracking-[.16em]">Agent Card</span>
                <span className="ml-auto text-xs text-[var(--color-muted)]">confidence: {Math.round(card.confidence * 100)}%</span>
              </div>
              <div className="text-xs space-y-1 text-[var(--color-muted)]">
                <div>Model: {card.model || '—'}</div>
                <div>Memories: {card.memory_count} · Entities: {card.entity_count} · Conclusions: {card.conclusion_count} · Summaries: {card.summary_count}</div>
                <div>Trust: ✓ {card.confirmed_count} · ⚠ {card.contradicted_count}</div>
                {card.representation && <div className="text-[var(--color-text)] mt-2 p-2 border border-[rgba(102,252,241,.1)]">{card.representation}</div>}
              </div>
              {card.conclusions.length > 0 && (
                <div>
                  <div className="text-[var(--color-cyan)] uppercase text-xs tracking-[.16em] mb-1">Conclusions</div>
                  <ul className="list-disc list-inside space-y-1 text-xs text-[var(--color-muted)] m-0">
                    {card.conclusions.map((c, i) => <li key={i}>{c}</li>)}
                  </ul>
                </div>
              )}
              {card.recent_memories.length > 0 && (
                <div>
                  <div className="text-[var(--color-cyan)] uppercase text-xs tracking-[.16em] mb-1">Top Memories</div>
                  {card.recent_memories.slice(0, 5).map((m) => (
                    <div key={m.id} className="border-b border-[rgba(102,252,241,.1)] py-1 text-xs">
                      <span className="text-[var(--color-cyan)]">[{m.memory_type}]</span> {m.content.slice(0, 200)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
