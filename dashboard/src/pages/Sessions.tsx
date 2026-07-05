import { useQuery } from '@tanstack/react-query';
import { fetchSessions, fetchSessionDetail } from '../api/nexus';
import { useState } from 'react';

export default function Sessions() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data: sessions } = useQuery({ queryKey: ['sessions'], queryFn: () => fetchSessions(50), refetchInterval: 30000 });
  const { data: detail } = useQuery({
    queryKey: ['session-detail', selectedId],
    queryFn: () => fetchSessionDetail(selectedId!),
    enabled: !!selectedId,
  });

  return (
    <>
      <div className="flex items-center gap-4 mb-4">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Sessions</div>
          <h2 className="text-3xl m-0 mt-1">Raw Timeline · Provenance</h2>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 flex-1 min-h-0">
        <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4 overflow-auto">
          <h3 className="text-[.82rem] text-[var(--color-cyan)] uppercase tracking-[.16em] m-0 mb-3">Session Timeline</h3>
          {sessions?.map((s) => (
            <div
              key={s.id}
              className={`border p-2 cursor-pointer text-xs mb-1 ${selectedId === s.id ? 'border-[var(--color-cyan)] bg-[rgba(102,252,241,.08)]' : 'border-[rgba(102,252,241,.11)]'} hover:border-[var(--color-cyan)]`}
              onClick={() => setSelectedId(s.id)}>
              <b>{s.title || s.id.slice(0, 8)}</b>
              <div className="text-[var(--color-dim)]">{s.agent_id} · {s.project_key || '-'} · {s.message_count} msgs</div>
            </div>
          ))}
        </div>

        <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-4 overflow-auto">
          <h3 className="text-[.82rem] text-[var(--color-cyan)] uppercase tracking-[.16em] m-0 mb-3">Raw Messages</h3>
          {!detail && <div className="text-xs text-[var(--color-dim)]">Select a session to inspect.</div>}
          {detail && (
            <div className="text-xs font-mono space-y-3">
              <div className="border-b border-[rgba(102,252,241,.1)] pb-2 text-[var(--color-dim)]">
                SESSION: {detail.id}<br />
                AGENT: {detail.agent_id}<br />
                STARTED: {detail.started_at ? new Date(detail.started_at).toLocaleString() : ''}
              </div>
              {detail.messages?.slice(0, 50).map((m) => (
                <div key={m.id} className="border-l-2 border-[rgba(102,252,241,.15)] pl-2">
                  <div className="text-[var(--color-cyan2)]">[{m.role}] ≈{m.token_estimate} tokens</div>
                  <div className="text-[var(--color-text)] mt-0.5 whitespace-pre-wrap">{m.content.slice(0, 500)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
