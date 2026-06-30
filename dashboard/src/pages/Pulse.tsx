import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchMetrics, fetchMindLearningEvents, fetchMindProactiveLog, fetchSessions } from '../api/nexus';
import type { MetricsResponse, MindLearningEvent, MindProactiveLogItem, SessionItem } from '../types/nexus';

type Event = {
  ts: number;
  source: 'mind' | 'proactive' | 'session' | 'metric' | 'system';
  level: 'info' | 'success' | 'warn' | 'critical';
  text: string;
};

const LEVEL_COLOR: Record<string, string> = {
  info: 'var(--color-cyan)',
  success: 'var(--color-green)',
  warn: 'var(--color-amber)',
  critical: 'var(--color-red)',
};

const LEVEL_GLYPH: Record<string, string> = {
  info: '◆',
  success: '✓',
  warn: '⚠',
  critical: '✕',
};

export default function Pulse() {
  const { data: metrics } = useQuery<MetricsResponse>({ queryKey: ['metrics'], queryFn: fetchMetrics, refetchInterval: 5000 });
  const { data: learning } = useQuery<{ events: MindLearningEvent[] }>({
    queryKey: ['pulse-learning'],
    queryFn: () => fetchMindLearningEvents('default', 200),
    refetchInterval: 8000,
  });
  const { data: proactive } = useQuery<{ items: MindProactiveLogItem[] }>({
    queryKey: ['pulse-proactive'],
    queryFn: () => fetchMindProactiveLog('default', 200),
    refetchInterval: 8000,
  });
  const { data: sessions } = useQuery<Session[]>({
    queryKey: ['pulse-sessions'],
    queryFn: () => fetchSessions(50),
    refetchInterval: 15000,
  });

  const events: Event[] = [];
  if (learning?.events) {
    for (const e of learning.events) {
      events.push({
        ts: e.created_at ? new Date(e.created_at).getTime() : 0,
        source: 'mind',
        level: e.kind === 'limitation' ? 'warn' : e.kind === 'opinion_formed' ? 'success' : 'info',
        text: `${e.kind}: ${e.description}`,
      });
    }
  }
  if (proactive?.items) {
    for (const it of proactive.items) {
      events.push({
        ts: it.created_at ? new Date(it.created_at).getTime() : 0,
        source: 'proactive',
        level: it.used ? 'success' : 'info',
        text: `proactive→${it.agent_id}: ${it.content}`,
      });
    }
  }
  if (sessions) {
    for (const s of sessions) {
      if (s.started_at) {
        events.push({
          ts: new Date(s.started_at).getTime(),
          source: 'session',
          level: 'info',
          text: `session start: ${s.agent_id} · "${s.title ?? s.id}"`,
        });
      }
      if (s.ended_at) {
        events.push({
          ts: new Date(s.ended_at).getTime(),
          source: 'session',
          level: 'success',
          text: `session end: ${s.agent_id} · ${s.message_count} msgs`,
        });
      }
    }
  }
  if (metrics?.recent_events) {
    for (const e of metrics.recent_events) {
      events.push({
        ts: e.created_at ? new Date(e.created_at).getTime() : 0,
        source: 'metric',
        level: 'info',
        text: `${e.actor}: ${e.action}`,
      });
    }
  }
  events.sort((a, b) => b.ts - a.ts);

  // Filter
  const [srcFilter, setSrcFilter] = useState<Set<Event['source']>>(new Set(['mind', 'proactive', 'session', 'metric']));
  const filtered = events.filter((e) => srcFilter.has(e.source));

  // Live counter
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Title */}
      <div className="flex items-end gap-3">
        <div>
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.34em]">Real-Time Telemetry</div>
          <h2 className="text-3xl m-0 mt-1 nx-glow" style={{ color: 'var(--color-green)' }}>PULSE</h2>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {(['mind', 'proactive', 'session', 'metric'] as Event['source'][]).map((s) => (
            <button key={s} onClick={() => {
              const next = new Set(srcFilter);
              next.has(s) ? next.delete(s) : next.add(s);
              setSrcFilter(next);
            }} className={`px-2 py-1 text-[.6rem] uppercase tracking-[.14em] border transition-all ${srcFilter.has(s) ? 'border-[var(--color-line)] bg-[rgba(102,252,241,.08)] text-[var(--color-text)]' : 'border-[rgba(102,252,241,.15)] text-[var(--color-dim)]'}`}>{s}</button>
          ))}
        </div>
      </div>

      {/* Stat row */}
      <div className="grid grid-cols-5 gap-2">
        <Stat label="events / total" value={events.length} color="cyan" />
        <Stat label="mind" value={(learning?.events ?? []).length} color="violet" sub="learnings" />
        <Stat label="proactive" value={(proactive?.items ?? []).length} color="magenta" sub="surfaces" />
        <Stat label="sessions" value={(sessions ?? []).length} color="amber" sub="recent" />
        <Stat label="last 24h" value={Object.values(metrics?.last_24h ?? {}).reduce((a, b) => a + b, 0)} color="green" sub="all sources" />
      </div>

      {/* Live terminal */}
      <div className="nx-card flex-1 min-h-0 overflow-auto nx-mono text-[.72rem] leading-relaxed">
        <div className="sticky top-0 bg-[rgba(2,4,12,.92)] backdrop-blur-sm py-1 mb-2 border-b border-[var(--color-line)] flex items-center gap-2 z-10">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-green)] nx-pulse" />
          <span className="text-[.6rem] text-[var(--color-cyan)] uppercase tracking-[.2em]">NEXUS:// pulse.live</span>
          <span className="ml-auto text-[var(--color-dim)] tabular-nums text-[.65rem]">{new Date(now).toISOString().slice(11, 19)} UTC</span>
          <span className="text-[var(--color-dim)] text-[.65rem]">· {filtered.length} events shown</span>
        </div>
        <div className="space-y-0.5">
          {filtered.slice(0, 300).map((e, i) => (
            <div key={i} className="flex items-start gap-2 hover:bg-[rgba(102,252,241,.04)] px-1 py-0.5 border-l-2 border-transparent hover:border-[var(--color-cyan)] transition-colors">
              <span className="text-[var(--color-dim)] tabular-nums w-20 shrink-0">
                {e.ts ? new Date(e.ts).toISOString().slice(11, 19) : '—'}
              </span>
              <span className="text-[.6rem] uppercase tracking-[.1em] w-16 shrink-0 text-center" style={{ color: 'var(--color-violet)' }}>{e.source}</span>
              <span style={{ color: LEVEL_COLOR[e.level] }} className="w-3 text-center shrink-0">{LEVEL_GLYPH[e.level]}</span>
              <span className="text-[var(--color-text)] break-words flex-1">{e.text}</span>
            </div>
          ))}
          {filtered.length === 0 && <div className="text-[var(--color-dim)] text-center py-8">No events match the current filter.</div>}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, color = 'cyan', sub }: { label: string; value: number; color?: string; sub?: string }) {
  return (
    <div className="nx-card relative overflow-hidden">
      <div className="text-[.6rem] text-[var(--color-muted)] uppercase tracking-[.22em]">{label}</div>
      <div className="text-2xl tabular-nums mt-1 nx-glow" style={{ color: `var(--color-${color})` }}>{value.toLocaleString()}</div>
      {sub && <div className="text-[.55rem] text-[var(--color-dim)] mt-0.5">{sub}</div>}
    </div>
  );
}

// Type for sessions list — the API returns array
type Session = SessionItem;
