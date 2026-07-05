import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchMindDashboard, fetchMindOpinions, fetchMindLearningEvents, fetchMindProactiveLog, mindThink } from '../api/nexus';
import type { MindDashboardResponse, MindThinkResponse, MindOpinion, MindLearningEvent, MindProactiveLogItem } from '../types/nexus';

const STANCE_COLOR: Record<string, string> = {
  positive: 'var(--color-green)',
  negative: 'var(--color-red)',
  neutral: 'var(--color-muted)',
};

const STANCE_GLYPH: Record<string, string> = {
  positive: '◈',
  negative: '◬',
  neutral: '◌',
};

const LEARN_GLYPH: Record<string, string> = {
  interaction_learning: '◉',
  pattern: '◆',
  capability: '✦',
  limitation: '⚠',
  opinion_formed: '✧',
  identity_update: '◈',
};

const LEARN_COLOR: Record<string, string> = {
  interaction_learning: 'var(--color-cyan)',
  pattern: 'var(--color-violet)',
  capability: 'var(--color-green)',
  limitation: 'var(--color-red)',
  opinion_formed: 'var(--color-magenta)',
  identity_update: 'var(--color-amber)',
};

function timeAgo(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso).getTime();
  const s = Math.floor((Date.now() - d) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function Observatory() {
  const { data, isLoading, error } = useQuery<MindDashboardResponse>({
    queryKey: ['mind-dashboard'],
    queryFn: () => fetchMindDashboard('default'),
    refetchInterval: 10000,
  });
  const { data: opinionsResp } = useQuery<{ opinions: MindOpinion[] }>({
    queryKey: ['mind-opinions'],
    queryFn: () => fetchMindOpinions('default'),
    refetchInterval: 15000,
  });
  const { data: learning } = useQuery<{ events: MindLearningEvent[] }>({
    queryKey: ['mind-learning'],
    queryFn: () => fetchMindLearningEvents('default', 80),
    refetchInterval: 10000,
  });
  const { data: proactive } = useQuery<{ items: MindProactiveLogItem[] }>({
    queryKey: ['mind-proactive'],
    queryFn: () => fetchMindProactiveLog('default', 80),
    refetchInterval: 10000,
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
    } finally {
      setThinking(false);
    }
  };

  // Live pulse animation
  const [pulse, setPulse] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setPulse((p) => (p + 1) % 100), 80);
    return () => clearInterval(id);
  }, []);

  const opinions: MindOpinion[] = opinionsResp?.opinions ?? (data ? Object.values(data.opinions) : []);
  const relationships = data ? Object.values(data.relationships) : [];
  const patterns = data?.identity.learned_patterns ?? [];
  const traits = data?.identity.core_traits ?? [];
  const caps = data?.identity.capabilities ?? [];
  const limits = data?.identity.limitations ?? [];

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Title */}
      <div className="flex items-end gap-3">
        <div>
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.34em]">Live Mind State</div>
          <h2 className="text-3xl m-0 mt-1 nx-glow" style={{ color: 'var(--color-amber)' }}>MIND OBSERVATORY</h2>
        </div>
        <div className="ml-auto flex items-center gap-2 border border-[var(--color-line)] bg-[rgba(255,209,102,.04)] px-3 py-1.5">
          <span className="w-2 h-2 rounded-full" style={{ background: 'var(--color-amber)', boxShadow: '0 0 10px var(--color-amber)', animation: 'pulse 1.4s infinite' }} />
          <span className="text-[.65rem] uppercase tracking-[.18em]" style={{ color: 'var(--color-amber)' }}>mind online</span>
        </div>
      </div>

      <div className="grid grid-cols-[1.4fr_1fr] gap-3 flex-1 min-h-0">
        {/* Left column */}
        <div className="flex flex-col gap-3 min-h-0">
          {/* Identity / live brain */}
          <div className="nx-card relative overflow-hidden" style={{ minHeight: 220 }}>
            <div className="flex items-center justify-between mb-2">
              <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Identity · Self Model</div>
              <div className="text-[.6rem] text-[var(--color-muted)]">pulse #{pulse.toString().padStart(3, '0')}</div>
            </div>
            {isLoading && <div className="text-[var(--color-dim)] text-sm">Awakening mind…</div>}
            {error && <div className="text-[var(--color-red)] text-sm">Failed: {String(error)}</div>}
            {data && (
              <div className="grid grid-cols-[1fr_140px] gap-3 h-full">
                <div className="text-[var(--color-text)] text-[.78rem] leading-relaxed whitespace-pre-wrap overflow-auto pr-2">
                  {data.self_description}
                </div>
                <div className="flex flex-col gap-1 text-[.7rem]">
                  <Stat label="patterns" value={data.stats.patterns_learned} color="violet" />
                  <Stat label="opinions" value={data.stats.opinions_held} color="magenta" />
                  <Stat label="capabilities" value={data.stats.capabilities} color="green" />
                  <Stat label="limits" value={data.stats.limitations} color="red" />
                  <Stat label="relations" value={data.stats.relationships} color="amber" />
                  <Stat label="convos" value={data.stats.active_conversations} color="cyan" />
                </div>
              </div>
            )}
          </div>

          {/* Core traits + caps + limits */}
          <div className="grid grid-cols-3 gap-3">
            <div className="nx-card">
              <div className="text-[.6rem] text-[var(--color-cyan)] uppercase tracking-[.22em] mb-2">Core Traits</div>
              <div className="space-y-1">
                {traits.slice(0, 6).map((t, i) => (
                  <div key={i} className="text-[.72rem] text-[var(--color-text)] border-l-2 border-[var(--color-cyan)] pl-2 py-0.5">▸ {t}</div>
                ))}
                {traits.length === 0 && <div className="text-[var(--color-dim)] text-[.7rem]">none recorded</div>}
              </div>
            </div>
            <div className="nx-card">
              <div className="text-[.6rem] text-[var(--color-green)] uppercase tracking-[.22em] mb-2">Capabilities</div>
              <div className="flex flex-wrap gap-1">
                {caps.slice(0, 20).map((c, i) => (
                  <span key={i} className="text-[.65rem] px-1.5 py-0.5 border border-[rgba(99,255,159,.4)] text-[var(--color-green)] bg-[rgba(99,255,159,.06)]">✓ {c}</span>
                ))}
                {caps.length === 0 && <span className="text-[var(--color-dim)] text-[.7rem]">none</span>}
              </div>
            </div>
            <div className="nx-card nx-card-violet">
              <div className="text-[.6rem] text-[var(--color-red)] uppercase tracking-[.22em] mb-2">Limitations</div>
              <div className="flex flex-wrap gap-1">
                {limits.slice(0, 20).map((l, i) => (
                  <span key={i} className="text-[.65rem] px-1.5 py-0.5 border border-[rgba(255,84,112,.4)] text-[var(--color-red)] bg-[rgba(255,84,112,.06)]">⚠ {l}</span>
                ))}
                {limits.length === 0 && <span className="text-[var(--color-dim)] text-[.7rem]">none</span>}
              </div>
            </div>
          </div>

          {/* Learned patterns */}
          <div className="nx-card flex-1 min-h-0 overflow-auto">
            <div className="text-[.6rem] text-[var(--color-violet)] uppercase tracking-[.22em] mb-2 sticky top-0 bg-[rgba(4,10,24,.85)] backdrop-blur py-1">Learned Patterns</div>
            <div className="space-y-1.5">
              {patterns.slice().reverse().slice(0, 30).map((p, i) => (
                <div key={i} className="border-b border-[rgba(185,103,255,.1)] pb-1.5 text-[.72rem]">
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--color-violet)] tabular-nums text-[.65rem]">[{p.importance.toFixed(2)}]</span>
                    <span className="text-[var(--color-text)] flex-1">{p.description}</span>
                    {p.evidence_count > 1 && <span className="text-[var(--color-amber)] text-[.6rem]">×{p.evidence_count}</span>}
                    <span className="text-[var(--color-dim)] text-[.6rem]">{timeAgo(p.learned_at)}</span>
                  </div>
                </div>
              ))}
              {patterns.length === 0 && <div className="text-[var(--color-dim)] text-[.7rem]">No patterns learned yet — ask the mind something to start learning.</div>}
            </div>
          </div>
        </div>

        {/* Right column */}
        <div className="flex flex-col gap-3 min-h-0">
          {/* Ask the mind */}
          <div className="nx-card">
            <div className="text-[.6rem] text-[var(--color-cyan)] uppercase tracking-[.22em] mb-2">Probe the Mind</div>
            <div className="flex gap-2">
              <input
                className="flex-1 bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] px-2 py-1.5 text-[.8rem] text-[var(--color-text)] outline-none"
                placeholder="Ask the mind something…"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && ask()}
              />
              <select value={depth} onChange={(e) => setDepth(e.target.value as 'fast' | 'standard' | 'deep')}
                className="bg-[rgba(102,252,241,.045)] border border-[rgba(102,252,241,.22)] text-[.7rem] px-2 text-[var(--color-text)] outline-none">
                <option value="fast">fast</option>
                <option value="standard">standard</option>
                <option value="deep">deep</option>
              </select>
              <button onClick={ask} disabled={thinking}
                className="border border-[var(--color-amber)] text-[var(--color-amber)] px-3 text-[.7rem] uppercase tracking-[.16em] hover:bg-[rgba(255,209,102,.08)] disabled:opacity-30">
                {thinking ? '·  ·  ·' : 'TRANSMIT'}
              </button>
            </div>
          </div>

          {/* Live response */}
          <div className="nx-card flex-1 min-h-0 overflow-auto nx-mono text-[.7rem] leading-relaxed">
            {thinkError && <div className="text-[var(--color-red)]">// mind error: {thinkError}</div>}
            {!answer && !thinkError && (
              <div className="text-[var(--color-dim)]">
                <div>// observatory standby</div>
                <div>// awaiting query</div>
                <div className="nx-pulse inline-block mt-2" style={{ background: 'var(--color-amber)' }} />
              </div>
            )}
            {answer && (
              <div className="space-y-2">
                {answer.answer && <div className="text-[var(--color-text)] whitespace-pre-wrap text-[.78rem] leading-relaxed">» {answer.answer}</div>}
                {answer.clarifying_question && (
                  <div className="text-[var(--color-amber)] border-l-2 border-[var(--color-amber)] pl-2">? {answer.clarifying_question}</div>
                )}
                <div className="flex flex-wrap gap-2 text-[.6rem] border-t border-[var(--color-line)] pt-1.5">
                  <span className="text-[var(--color-muted)]">conf <b className="text-[var(--color-cyan)] tabular-nums">{answer.confidence.toFixed(2)}</b></span>
                  <span className="text-[var(--color-muted)]">mem <b className="text-[var(--color-violet)] tabular-nums">{answer.memories_cited.length}</b></span>
                  <span className="text-[var(--color-muted)]">proactive <b className="text-[var(--color-magenta)] tabular-nums">{answer.proactive_context.length}</b></span>
                  <span className="text-[var(--color-muted)]">opinions <b className="text-[var(--color-amber)] tabular-nums">{answer.opinions_expressed.length}</b></span>
                </div>
                {answer.proactive_context.length > 0 && (
                  <details open className="border border-[var(--color-line)] p-1.5">
                    <summary className="text-[var(--color-cyan)] text-[.6rem] uppercase tracking-[.18em] cursor-pointer">proactive context</summary>
                    {answer.proactive_context.map((p, i) => (
                      <div key={i} className="text-[.65rem] text-[var(--color-muted)] ml-2 mt-1">— <span className="text-[var(--color-violet)]">[{p.type}]</span> {p.content} <span className="text-[var(--color-dim)]">rel {p.relevance.toFixed(2)}</span></div>
                    ))}
                  </details>
                )}
                {answer.reasoning_trace?.trace && answer.reasoning_trace.trace.length > 0 && (
                  <details className="border border-[var(--color-line)] p-1.5">
                    <summary className="text-[var(--color-cyan)] text-[.6rem] uppercase tracking-[.18em] cursor-pointer">reasoning trace ({answer.reasoning_trace.trace.length} steps)</summary>
                    {answer.reasoning_trace.trace.map((s, i) => (
                      <div key={i} className="text-[.65rem] text-[var(--color-muted)] ml-2 mt-1">
                        <span className="text-[var(--color-violet)]">▸ {s.name}</span>
                        <span className="text-[var(--color-dim)]"> conf {s.confidence?.toFixed(2) ?? '—'}</span>
                        <div className="text-[var(--color-text)] pl-2 border-l border-[var(--color-line)] ml-1 mt-0.5">{(s.output ?? '').slice(0, 200)}</div>
                      </div>
                    ))}
                  </details>
                )}
                {answer.opinions_expressed.length > 0 && (
                  <details className="border border-[var(--color-line)] p-1.5">
                    <summary className="text-[var(--color-cyan)] text-[.6rem] uppercase tracking-[.18em] cursor-pointer">opinions expressed</summary>
                    {answer.opinions_expressed.map((o, i) => (
                      <div key={i} className="text-[.65rem] text-[var(--color-muted)] ml-2 mt-1">
                        — {o.topic}: <span style={{ color: STANCE_COLOR[o.stance] }}>{o.stance}</span> (strength {o.strength.toFixed(2)}, {o.evidence_count} ev)
                      </div>
                    ))}
                  </details>
                )}
              </div>
            )}
          </div>

          {/* Live opinions + relationships */}
          <div className="grid grid-cols-2 gap-3">
            <div className="nx-card nx-card-violet max-h-48 overflow-auto">
              <div className="text-[.6rem] text-[var(--color-violet)] uppercase tracking-[.22em] mb-2 sticky top-0 bg-[rgba(4,10,24,.85)] backdrop-blur py-1">Active Opinions · {opinions.length}</div>
              <div className="space-y-1.5">
                {opinions.slice(0, 10).map((o) => (
                  <div key={o.topic} className="text-[.65rem] border-b border-[rgba(185,103,255,.12)] pb-1">
                    <div className="flex items-center gap-1.5">
                      <span style={{ color: STANCE_COLOR[o.stance] }}>{STANCE_GLYPH[o.stance]}</span>
                      <span className="text-[var(--color-text)] flex-1 truncate">{o.topic}</span>
                      <span className="text-[var(--color-dim)] tabular-nums">{(o.strength * 100).toFixed(0)}%</span>
                    </div>
                    {o.rationale && <div className="text-[var(--color-muted)] text-[.6rem] pl-3 mt-0.5">{o.rationale.slice(0, 100)}</div>}
                  </div>
                ))}
                {opinions.length === 0 && <div className="text-[var(--color-dim)] text-[.7rem]">No opinions held yet</div>}
              </div>
            </div>
            <div className="nx-card max-h-48 overflow-auto">
              <div className="text-[.6rem] text-[var(--color-amber)] uppercase tracking-[.22em] mb-2 sticky top-0 bg-[rgba(4,10,24,.85)] backdrop-blur py-1">Relationships · {relationships.length}</div>
              <div className="space-y-1.5">
                {relationships.slice(0, 10).map((r) => (
                  <div key={r.agent_id} className="text-[.65rem] border-b border-[rgba(255,209,102,.12)] pb-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[var(--color-text)] flex-1 truncate">{r.agent_id}</span>
                      <span className="text-[var(--color-amber)] tabular-nums">trust {(r.trust_level * 100).toFixed(0)}</span>
                    </div>
                    <div className="text-[.6rem] text-[var(--color-dim)] pl-1">×{r.interaction_count} interactions</div>
                  </div>
                ))}
                {relationships.length === 0 && <div className="text-[var(--color-dim)] text-[.7rem]">No relationships yet</div>}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom row: live learning + proactive events */}
      <div className="grid grid-cols-2 gap-3 h-44">
        <div className="nx-card overflow-auto">
          <div className="text-[.6rem] text-[var(--color-cyan)] uppercase tracking-[.22em] mb-2 sticky top-0 bg-[rgba(4,10,24,.85)] backdrop-blur py-1">Learning Stream · {learning?.events?.length ?? 0} events</div>
          <div className="space-y-1">
            {learning?.events?.slice(0, 20).map((e, i) => (
              <div key={i} className="text-[.65rem] border-b border-[rgba(102,252,241,.06)] pb-1 flex items-start gap-2">
                <span style={{ color: LEARN_COLOR[e.kind] || 'var(--color-muted)' }} className="text-[.9rem] leading-none">{LEARN_GLYPH[e.kind] || '◉'}</span>
                <span className="text-[var(--color-cyan)] text-[.6rem] uppercase w-24 shrink-0 truncate">{e.kind}</span>
                <span className="text-[var(--color-text)] flex-1">{e.description.slice(0, 80)}</span>
                <span className="text-[var(--color-dim)] text-[.6rem] tabular-nums w-12 text-right">{timeAgo(e.created_at)}</span>
              </div>
            ))}
            {(!learning?.events || learning.events.length === 0) && <div className="text-[var(--color-dim)] text-[.7rem]">No learning events yet</div>}
          </div>
        </div>
        <div className="nx-card overflow-auto">
          <div className="text-[.6rem] text-[var(--color-magenta)] uppercase tracking-[.22em] mb-2 sticky top-0 bg-[rgba(4,10,24,.85)] backdrop-blur py-1">Proactive Surfaces · {proactive?.items?.length ?? 0} items</div>
          <div className="space-y-1">
            {proactive?.items?.slice(0, 20).map((it, i) => (
              <div key={i} className="text-[.65rem] border-b border-[rgba(255,60,172,.1)] pb-1">
                <div className="flex items-center gap-2">
                  <span className="text-[var(--color-magenta)] text-[.6rem] uppercase w-20 shrink-0">{it.item_type}</span>
                  <span className="text-[var(--color-violet)] text-[.6rem]">→ {it.agent_id}</span>
                  <span className="text-[var(--color-dim)] text-[.6rem] ml-auto tabular-nums">rel {it.relevance.toFixed(2)}</span>
                </div>
                <div className="text-[var(--color-text)] mt-0.5">{it.content.slice(0, 100)}</div>
                <div className="text-[var(--color-dim)] text-[.55rem] mt-0.5">{timeAgo(it.created_at)}{it.used ? ' · ✓ used' : ''}</div>
              </div>
            ))}
            {(!proactive?.items || proactive.items.length === 0) && <div className="text-[var(--color-dim)] text-[.7rem]">No proactive surfaces yet</div>}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, color = 'cyan' }: { label: string; value: number; color?: string }) {
  return (
    <div className="border border-[var(--color-line)] bg-[rgba(102,252,241,.04)] px-2 py-1.5 flex items-center justify-between">
      <span className="text-[.55rem] text-[var(--color-muted)] uppercase tracking-[.18em]">{label}</span>
      <span className="text-base tabular-nums" style={{ color: `var(--color-${color})` }}>{value}</span>
    </div>
  );
}
