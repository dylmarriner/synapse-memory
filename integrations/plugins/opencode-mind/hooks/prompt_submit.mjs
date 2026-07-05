// prompt_submit.mjs — OpenCode hook that injects just-in-time
// context from the Living Mind before each user prompt.
import { setTimeout as sleep } from 'node:timers/promises';

const NEXUS_URL = process.env.NEXUS_URL || 'http://localhost:7777';
const NEXUS_SECRET = process.env.NEXUS_SECRET || '';
const MIND_ID = process.env.MIND_ID || 'default';
const AGENT_ID = process.env.AGENT_ID || 'opencode';

async function mindThink(question) {
  if (!NEXUS_SECRET) return null;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 5000);
    const r = await fetch(`${NEXUS_URL}/v1/mind/think`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${NEXUS_SECRET}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        mind_id: MIND_ID,
        question,
        context: { agent_id: AGENT_ID },
        reasoning_depth: 'fast',
      }),
      signal: ctrl.signal,
    });
    clearTimeout(t);
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  }
}

async function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.on('data', (chunk) => (data += chunk));
    process.stdin.on('end', () => resolve(data));
    setTimeout(() => resolve(data), 200);
  });
}

async function main() {
  const stdin = await readStdin();
  let userPrompt = '';
  try {
    userPrompt = (JSON.parse(stdin).prompt || '').slice(0, 500);
  } catch (e) {
    // ignore — empty stdin
  }
  if (!userPrompt) return;

  const think = await mindThink(userPrompt);
  if (!think) return;

  const sections = [];

  const items = think.proactive_context || [];
  if (items.length > 0) {
    const lines = ['## Living Mind: Relevant Context\n'];
    for (const item of items.slice(0, 3)) {
      lines.push(`- [${item.type}] ${item.content} (relevance ${item.relevance.toFixed(2)})`);
    }
    sections.push(lines.join('\n'));
  }

  if (think.clarifying_question) {
    sections.push(`## Living Mind: Clarifying Question\n${think.clarifying_question}`);
  }

  if (sections.length > 0) {
    process.stdout.write(sections.join('\n\n') + '\n');
  }
}

main().catch(() => { /* never fail a prompt */ });
