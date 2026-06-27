/**
 * OpenClaw + Living Mind integration
 *
 * Wires OpenClaw to a running Nexus server's Living Mind.  At session
 * start, the mind's identity + proactive context + opinions are
 * injected into the agent's system prompt.  At every tool use, the
 * observation is captured for the mind to learn from.  At session
 * end, a summary is saved for continuity.
 *
 * Required env:
 *   NEXUS_URL     - base URL of the Nexus server
 *   NEXUS_SECRET  - bearer token
 *   MIND_ID      - which mind to query, default "default"
 *   AGENT_ID     - which agent is starting, default "openclaw"
 */
import type { OpenClawPluginAPI } from "@openclaw/plugin-sdk";

const NEXUS_URL = process.env.NEXUS_URL || "http://localhost:7777";
const NEXUS_SECRET = process.env.NEXUS_SECRET || "";
const MIND_ID = process.env.MIND_ID || "default";
const AGENT_ID = process.env.AGENT_ID || "openclaw";

async function mindCall<T = any>(path: string, opts: RequestInit = {}): Promise<T | null> {
  if (!NEXUS_SECRET) return null;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 5000);
    const r = await fetch(`${NEXUS_URL}${path}`, {
      ...opts,
      headers: {
        Authorization: `Bearer ${NEXUS_SECRET}`,
        "Content-Type": "application/json",
        ...(opts.headers || {}),
      },
      signal: ctrl.signal,
    });
    clearTimeout(t);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch (e) {
    return null;
  }
}

function buildBriefing(sections: string[]): string {
  return sections.filter(Boolean).join("\n\n");
}

export default function mindPlugin(api: OpenClawPluginAPI) {
  // --- Session start: build and inject the mind's briefing ----
  api.on("session_start", async () => {
    const sections: string[] = [];

    // 1. Mind identity
    const identity = await mindCall<any>(`/v1/mind/identity/${MIND_ID}`);
    if (identity?.description) {
      sections.push(identity.description);
    }

    // 2. Proactive context
    const think = await mindCall<any>("/v1/mind/think", {
      method: "POST",
      body: JSON.stringify({
        mind_id: MIND_ID,
        question: "What should I know right now?",
        context: { agent_id: AGENT_ID, proactive_only: true },
      }),
    });
    if (think?.proactive_context?.length) {
      const lines = ["## Proactive Context (from the Living Mind)\n"];
      for (const item of think.proactive_context.slice(0, 5)) {
        lines.push(`- [${item.type}] ${item.content} (relevance ${item.relevance.toFixed(2)})`);
      }
      sections.push(lines.join("\n"));
    }

    // 3. Opinions
    const opinions = await mindCall<any>(`/v1/mind/opinions/${MIND_ID}`);
    const ops = opinions?.opinions;
    if (ops && typeof ops === "object" && Object.keys(ops).length > 0) {
      const lines = ["## Mind's Opinions\n"];
      for (const [topic, op] of Object.entries(ops).slice(0, 3)) {
        if (!op) continue;
        lines.push(`- **${topic}**: ${op.stance} (strength ${op.strength.toFixed(2)}, ${op.evidence_count} pieces of evidence)`);
      }
      sections.push(lines.join("\n"));
    }

    const briefing = buildBriefing(sections);
    if (briefing) {
      await api.injectSystemPrompt(briefing);
    }
  });

  // --- Prompt submit: just-in-time context for the current prompt ----
  api.on("prompt_submit", async (event) => {
    const prompt = event?.prompt?.slice(0, 500) || "";
    if (!prompt) return;
    const think = await mindCall<any>("/v1/mind/think", {
      method: "POST",
      body: JSON.stringify({
        mind_id: MIND_ID,
        question: prompt,
        context: { agent_id: AGENT_ID },
        reasoning_depth: "fast",
      }),
    });
    if (!think) return;
    const sections: string[] = [];
    const items = think.proactive_context || [];
    if (items.length > 0) {
      const lines = ["## Living Mind: Relevant Context\n"];
      for (const item of items.slice(0, 3)) {
        lines.push(`- [${item.type}] ${item.content} (relevance ${item.relevance.toFixed(2)})`);
      }
      sections.push(lines.join("\n"));
    }
    if (think.clarifying_question) {
      sections.push(`## Living Mind: Clarifying Question\n${think.clarifying_question}`);
    }
    const context = buildBriefing(sections);
    if (context) {
      await api.injectContext(context);
    }
  });

  // --- Post-tool-use: capture the observation for the mind ----
  api.on("post_tool_use", async (event) => {
    const toolName = event?.tool_name || "";
    if (!toolName) return;
    const observation = `Used ${toolName}: ${JSON.stringify(event?.tool_input || {}).slice(0, 300)}`;
    await mindCall("/v1/memory/save", {
      method: "POST",
      body: JSON.stringify({
        content: observation,
        agent_id: AGENT_ID,
        memory_type: "experience",
        importance: 0.4,
        tags: ["tool_use", toolName.toLowerCase(), "auto_capture"],
        metadata: { mind_id: MIND_ID, source: "openclaw_post_tool_use" },
      }),
    });
  });

  // --- Session end: save a summary so the next session has continuity ----
  api.on("session_end", async () => {
    await mindCall("/v1/memory/save", {
      method: "POST",
      body: JSON.stringify({
        content: `Session with ${AGENT_ID} via OpenClaw`,
        agent_id: AGENT_ID,
        memory_type: "experience",
        importance: 0.7,
        tags: ["session_summary", AGENT_ID],
        metadata: { mind_id: MIND_ID, source: "openclaw_session_end" },
      }),
    });
  });
}
