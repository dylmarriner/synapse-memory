// session_start.mjs — OpenCode hook that injects a Living Mind
// briefing at the start of every session.  Run via the OpenCode
// hook system:  "session_start": "node session_start.mjs"
//
// Environment:
//   NEXUS_URL    — base URL of the Nexus server
//   NEXUS_SECRET — bearer token
//   MIND_ID      — which mind to query (default "default")
//   AGENT_ID     — which agent is starting (default "opencode")
import { setTimeout as sleep } from 'node:timers/promises';

const NEXUS_URL = process.env.NEXUS_URL || 'http://localhost:7777';
const NEXUS_SECRET = process.env.NEXUS_SECRET || '';
const MIND_ID = process.env.MIND_ID || 'default';
const AGENT_ID = process.env.AGENT_ID || 'opencode';

async function mindCall(path, opts = {}) {
  if (!NEXUS_SECRET) return null;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 5000);
    const r = await fetch(`${NEXUS_URL}${path}`, {
      ...opts,
      headers: {
        'Authorization': `Bearer ${NEXUS_SECRET}`,
        'Content-Type': 'application/json',
        ...(opts.headers || {}),
      },
      signal: ctrl.signal,
    });
    clearTimeout(t);
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  }
}

async function main() {
  const sections = [];

  // 1. Mind identity
  const identity = await mindCall(`/v1/mind/identity/${MIND_ID}`);
  if (identity?.description) sections.push(identity.description);

  // 2. Proactive context
  const think = await mindCall('/v1/mind/think', {
    method: 'POST',
    body: JSON.stringify({
      mind_id: MIND_ID,
      question: 'What should I know right now?',
      context: { agent_id: AGENT_ID, proactive_only: true },
    }),
  });
  if (think?.proactive_context?.length) {
    const lines = ['## Proactive Context (from the Living Mind)\n'];
    for (const item of think.proactive_context.slice(0, 5)) {
      lines.push(`- [${item.type}] ${item.content} (relevance ${item.relevance.toFixed(2)})`);
    }
    sections.push(lines.join('\n'));
  }

  // 3. Mind's opinions
  const opinions = await mindCall(`/v1/mind/opinions/${MIND_ID}`);
  const ops = opinions?.opinions;
  if (ops && typeof ops === 'object' && Object.keys(ops).length > 0) {
    const lines = ['## Mind\'s Opinions\n'];
    for (const [topic, op] of Object.entries(ops).slice(0, 3)) {
      if (!op) continue;
      lines.push(`- **${topic}**: ${op.stance} (strength ${op.strength.toFixed(2)}, ${op.evidence_count} pieces of evidence)`);
    }
    sections.push(lines.join('\n'));
  }

  if (sections.length === 0) {
    // Mind not available; stay silent
    return;
  }

  // OpenCode hook system reads stdout to inject context
  process.stdout.write(sections.join('\n\n') + '\n');
}

main().catch(() => { /* never fail a session start */ });
