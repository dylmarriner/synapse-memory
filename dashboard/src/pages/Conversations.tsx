import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchMindConversations, fetchMindConversationTurns } from '../api/nexus';

export default function Conversations() {
  const [selected, setSelected] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ['mind-conversations'],
    queryFn: () => fetchMindConversations('default', 50),
    refetchInterval: 15000,
  });

  const { data: turnsData, isLoading: turnsLoading } = useQuery({
    queryKey: ['mind-conversation-turns', selected],
    queryFn: () => fetchMindConversationTurns(selected!),
    enabled: !!selected,
  });

  const conversations = data?.conversations ?? [];

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Conversations</div>
          <h2 className="text-3xl m-0 mt-1">Every Dialogue · Every Turn</h2>
        </div>
      </div>

      <div className="grid grid-cols-[320px_1fr] gap-4 flex-1 min-h-0">
        {/* List */}
        <div className="overflow-auto space-y-2">
          {isLoading && <div className="text-[var(--color-dim)] text-sm">Loading conversations…</div>}
          {error && <div className="text-[var(--color-red)] text-sm">Failed: {String(error)}</div>}
          {!isLoading && conversations.length === 0 && (
            <div className="text-[var(--color-dim)] text-sm">No conversations recorded yet.</div>
          )}
          {conversations.map((c) => (
            <button key={c.id} type="button"
              className={`w-full text-left border p-3 ${selected === c.id ? 'border-[var(--color-cyan)] bg-[rgba(102,252,241,.08)]' : 'border-[rgba(102,252,241,.11)] bg-[rgba(255,255,255,.025)]'} hover:border-[var(--color-cyan)]`}
              onClick={() => setSelected(c.id)}>
              <div className="flex items-center gap-2">
                <span className="text-sm text-[var(--color-text)]">{c.agent_id}</span>
                <span className={`ml-auto text-[.6rem] uppercase tracking-[.12em] px-1.5 py-0.5 ${c.open ? 'text-[var(--color-green)] border border-[rgba(99,255,159,.3)]' : 'text-[var(--color-dim)]'}`}>
                  {c.open ? 'open' : 'ended'}
                </span>
              </div>
              <div className="text-xs text-[var(--color-dim)] flex gap-2 mt-1">
                <span>{c.turn_count} turns</span>
                <span className="ml-auto">{c.started_at ? new Date(c.started_at).toLocaleString() : ''}</span>
              </div>
              {c.summary && <div className="text-xs text-[var(--color-muted)] mt-1 line-clamp-2">{c.summary}</div>}
            </button>
          ))}
        </div>

        {/* Turns */}
        <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4 overflow-auto">
          {!selected && <div className="text-[var(--color-dim)] text-sm">Select a conversation to see every turn and the mind's reasoning.</div>}
          {selected && turnsLoading && <div className="text-[var(--color-dim)] text-sm">Loading turns…</div>}
          {selected && turnsData && (
            <div className="space-y-4">
              {turnsData.turns.length === 0 && <div className="text-[var(--color-dim)] text-sm">No turns recorded.</div>}
              {turnsData.turns.map((t) => (
                <div key={t.turn_number} className="border-b border-[rgba(102,252,241,.1)] pb-3">
                  <div className="text-[.6rem] uppercase tracking-[.16em] text-[var(--color-dim)] mb-1">Turn {t.turn_number}</div>
                  <div className="text-sm text-[var(--color-cyan)] mb-1">▸ {t.agent_message}</div>
                  <div className="text-sm text-[var(--color-text)] whitespace-pre-wrap">
                    {t.mind_response?.answer ?? t.mind_response?.clarifying_question ?? '—'}
                  </div>
                  <div className="text-xs text-[var(--color-muted)] mt-1">
                    confidence {(t.confidence ?? 0).toFixed(2)}
                  </div>
                  {t.reasoning_trace?.trace && t.reasoning_trace.trace.length > 0 && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-[.62rem] uppercase tracking-[.14em] text-[var(--color-violet)]">
                        reasoning trace ({t.reasoning_trace.trace.length} steps)
                      </summary>
                      <div className="mt-1 space-y-0.5 font-mono text-[.68rem] text-[var(--color-dim)]">
                        {t.reasoning_trace.intent && <div>intent: {t.reasoning_trace.intent}</div>}
                        {t.reasoning_trace.trace.map((s, i) => (
                          <div key={i}><span className="text-[var(--color-violet)]">{s.name}</span> → {s.output}</div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
