import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchMindDashboard, mindThink } from '../api/nexus';
import type { MindThinkResponse } from '../types/nexus';

const STANCE_COLOR: Record<string, string> = {
  positive: 'var(--color-green)',
  negative: 'var(--color-red)',
  neutral: 'var(--color-muted)',
};

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-[rgba(102,252,241,.15)] bg-[rgba(102,252,241,.04)] p-3 text-center">
      <div className="text-2xl tabular-nums text-[var(--color-cyan)]">{value}</div>
      <div className="text-[.62rem] uppercase tracking-[.16em] text-[var(--color-dim)] mt-1">{label}</div>
    </div>
  );
}

export default function Mind() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['mind-dashboard'],
    queryFn: () => fetchMindDashboard('default'),
    refetchInterval: 15000,
  });

  const [question, setQuestion] = useState('');
  const [depth, setDepth] = useState<'fast' | 'standard' | 'deep'>('standard');
  const [thinking, setThinking] = useState(false);
  const [answer, setAnswer] = useState<MindThinkResponse | null>(null);
  const [thinkError, setThinkError] = useState('');

  const ask = async () => {
    if (!question.trim()) return;
    setThinking(true);
    setThinkError('');
    try {
      const r = await mindThink({ question: question.trim(), reasoning_depth: depth });
      setAnswer(r);
    } catch (e) {
      setThinkError(e instanceof Error ? e.message : String(e));
      setAnswer(null);
    } finally {
      setThinking(false);
    }
  };

  const opinions = data ? Object.values(data.opinions) : [];
  const relationships = data ? Object.values(data.relationships) : [];
  const patterns = data?.identity.learned_patterns ?? [];

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Living Mind</div>
          <h2 className="text-3xl m-0 mt-1">Reasoning Layer · Identity · Opinions</h2>
        </div>
        {data && (
          <span className="ml-auto text-xs text-[var(--color-muted)] uppercase tracking-[.16em]">
            mind: {data.mind_id}
          </span>
        )}
      </div>

      {isLoading && <div className="text-[var(--color-dim)] text-sm">Loading mind…</div>}
      {error && <div className="text-[var(--color-red)] text-sm">Mind load failed: {String(error)}</div>}

      {data && (
        <div className="grid grid-cols-[1fr_1fr] gap-4 flex-1 min-h-0">
          {/* Left column: identity + stats + patterns + relationships */}
          <div className="flex flex-col gap-4 min-h-0 overflow-auto pr-1">
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Patterns" value={data.stats.patterns_learned} />
              <Stat label="Opinions" value={data.stats.opinions_held} />
              <Stat label="Convos" value={data.stats.active_conversations} />
              <Stat label="Capabilities" value={data.stats.capabilities} />
              <Stat label="Limits" value={data.stats.limitations} />
              <Stat label="Relations" value={data.stats.relationships} />
            </div>

            <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4">
              <div className="text-[var(--color-cyan)] uppercase text-xs tracking-[.16em] mb-2">Identity</div>
              <pre className="whitespace-pre-wrap text-xs text-[var(--color-text)] leading-relaxed m-0 font-mono">
                {data.self_description}
              </pre>
            </div>

            <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4">
              <div className="text-[var(--color-cyan)] uppercase text-xs tracking-[.16em] mb-2">
                Learned Patterns (recent)
              </div>
              {patterns.length === 0 && <div className="text-[var(--color-dim)] text-xs">No patterns learned yet.</div>}
              <div className="space-y-1">
                {patterns
                  .slice(-12)
                  .reverse()
                  .map((p, i) => (
                    <div key={i} className="text-xs text-[var(--color-muted)] flex gap-2">
                      <span className="text-[var(--color-violet)] tabular-nums">[{p.importance.toFixed(2)}]</span>
                      <span className="text-[var(--color-text)]">{p.description}</span>
                      {p.evidence_count > 1 && <span className="text-[var(--color-dim)]">×{p.evidence_count}</span>}
                    </div>
                  ))}
              </div>
            </div>

            <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4">
              <div className="text-[var(--color-cyan)] uppercase text-xs tracking-[.16em] mb-2">Relationships</div>
              {relationships.length === 0 && (
                <div className="text-[var(--color-dim)] text-xs">No agent relationships yet.</div>
              )}
              <div className="space-y-1">
                {relationships.map((r) => (
                  <div key={r.agent_id} className="text-xs text-[var(--color-muted)] flex gap-3">
                    <span className="text-[var(--color-text)] truncate min-w-[120px]">{r.agent_id}</span>
                    <span>trust {r.trust_level.toFixed(2)}</span>
                    <span>×{r.interaction_count}</span>
                    {r.communication_style && <span className="text-[var(--color-dim)]">{r.communication_style}</span>}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right column: opinions + ask the mind */}
          <div className="flex flex-col gap-4 min-h-0">
            <div className="border border-[rgba(185,103,255,.25)] bg-[var(--color-panel)] p-4 max-h-[34%] overflow-auto">
              <div className="text-[var(--color-violet)] uppercase text-xs tracking-[.16em] mb-2">Active Opinions</div>
              {opinions.length === 0 && (
                <div className="text-[var(--color-dim)] text-xs">
                  No opinions held yet — ask the mind a question to form one.
                </div>
              )}
              <div className="space-y-2">
                {opinions.map((o) => (
                  <div key={o.topic} className="text-xs border-b border-[rgba(185,103,255,.12)] pb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-[var(--color-text)] font-semibold">{o.topic}</span>
                      <span className="uppercase tracking-[.1em]" style={{ color: STANCE_COLOR[o.stance] }}>
                        {o.stance}
                      </span>
                      <span className="ml-auto text-[var(--color-muted)]">
                        strength {o.strength.toFixed(2)} · {o.evidence_count} ev
                      </span>
                    </div>
                    {o.rationale && <div className="text-[var(--color-muted)] mt-1">{o.rationale}</div>}
                  </div>
                ))}
              </div>
            </div>

            <div className="flex gap-2">
              <input
                className="flex-1 bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] p-[9px_12px] text-sm text-[var(--color-text)] outline-none"
                placeholder="What do you know about…?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && ask()}
              />
              <select
                className="bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] text-sm text-[var(--color-text)] px-2 outline-none"
                value={depth}
                onChange={(e) => setDepth(e.target.value as 'fast' | 'standard' | 'deep')}>
                <option value="fast">fast</option>
                <option value="standard">standard</option>
                <option value="deep">deep</option>
              </select>
              <button
                className="border border-[var(--color-cyan)] text-[var(--color-cyan)] px-4 py-2 text-sm hover:bg-[rgba(102,252,241,.08)] disabled:opacity-30"
                onClick={ask}
                disabled={thinking}>
                {thinking ? 'thinking…' : 'Think'}
              </button>
            </div>

            <div className="flex-1 border border-[rgba(102,252,241,.2)] bg-[var(--color-panel2)] p-4 overflow-auto font-mono text-xs leading-relaxed min-h-0">
              {thinkError && <div className="text-[var(--color-red)]">MIND:// think failed: {thinkError}</div>}
              {!answer && !thinkError && (
                <div className="text-[var(--color-dim)]">MIND:// ask the mind a question to see reasoned output here.</div>
              )}
              {answer && (
                <div className="space-y-3">
                  {answer.answer && <div className="text-[var(--color-text)] whitespace-pre-wrap">{answer.answer}</div>}
                  {answer.clarifying_question && (
                    <div className="text-[var(--color-amber)]">[Question back] {answer.clarifying_question}</div>
                  )}
                  <div className="text-[var(--color-muted)]">
                    confidence {answer.confidence.toFixed(2)} · {answer.memories_cited.length} memories ·{' '}
                    {answer.proactive_context.length} proactive
                  </div>
                  {answer.proactive_context.length > 0 && (
                    <div>
                      <div className="text-[var(--color-cyan)] uppercase tracking-[.14em] mb-1">Proactive context</div>
                      {answer.proactive_context.map((p, i) => (
                        <div key={i} className="text-[var(--color-muted)]">
                          - <span className="text-[var(--color-violet)]">[{p.type}]</span> {p.content}{' '}
                          <span className="text-[var(--color-dim)]">(rel {p.relevance.toFixed(2)})</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {answer.opinions_expressed.length > 0 && (
                    <div>
                      <div className="text-[var(--color-cyan)] uppercase tracking-[.14em] mb-1">My take</div>
                      {answer.opinions_expressed.map((o, i) => (
                        <div key={i} className="text-[var(--color-muted)]">
                          - {o.topic}:{' '}
                          <span style={{ color: STANCE_COLOR[o.stance] }}>{o.stance}</span> (strength{' '}
                          {o.strength.toFixed(2)})
                        </div>
                      ))}
                    </div>
                  )}
                  {answer.reasoning_trace?.trace && answer.reasoning_trace.trace.length > 0 && (
                    <details className="text-[var(--color-dim)]">
                      <summary className="cursor-pointer text-[var(--color-cyan)] uppercase tracking-[.14em]">
                        Reasoning trace
                      </summary>
                      {answer.reasoning_trace.trace.map((s, i) => (
                        <div key={i} className="ml-2 mt-1">
                          <span className="text-[var(--color-violet)]">{s.name}</span> → {s.output}
                        </div>
                      ))}
                    </details>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
