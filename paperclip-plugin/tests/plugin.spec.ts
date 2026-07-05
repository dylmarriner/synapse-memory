import { afterEach, describe, expect, it, vi } from "vitest";
import { createTestHarness } from "@paperclipai/plugin-sdk/testing";
import manifest from "../src/manifest.js";
import plugin from "../src/worker.js";
import { deriveAgentId, normalizeImportance, paperclipKindToNexusType } from "../src/nexus-client.js";

const runCtx = {
  agentId: "agent-1",
  runId: "run-1",
  companyId: "company-1",
  projectId: "project-1",
};

function mockFetchJson(body: unknown, ok = true, status = 200) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => ({
    ok,
    status,
    statusText: ok ? "OK" : "Bad Gateway",
    text: async () => JSON.stringify(body),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Nexus Paperclip plugin", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("maps Paperclip memory kinds to Nexus types", () => {
    expect(paperclipKindToNexusType("identity")).toBe("world");
    expect(paperclipKindToNexusType("project_context")).toBe("world");
    expect(paperclipKindToNexusType("decision")).toBe("observation");
    expect(paperclipKindToNexusType("task_context")).toBe("experience");
    expect(paperclipKindToNexusType("error_pattern")).toBe("lesson");
  });

  it("normalizes importance scales", () => {
    expect(normalizeImportance(8)).toBe(0.8);
    expect(normalizeImportance(0.4)).toBe(0.4);
    expect(normalizeImportance(99)).toBe(1);
    expect(normalizeImportance(-1)).toBe(0);
  });

  it("derives stable Nexus agent IDs", () => {
    expect(deriveAgentId({ agentIdPrefix: "paperclip" }, { agentId: "agent-x", companyId: "company-x" })).toBe("agent-x");
    expect(deriveAgentId({ agentIdPrefix: "paperclip" }, { companyId: "company-x" })).toBe("paperclip:company:company-x");
  });

  it("registers tools and recalls Nexus memory", async () => {
    const fetchMock = mockFetchJson({
      results: [
        { content: "Remember to use Nexus for Paperclip memory", memory_type: "lesson", score: 0.91 },
      ],
    });
    const harness = createTestHarness({
      manifest,
      config: { nexusUrl: "http://nexus.test", nexusSecret: "secret", defaultLimit: 3 },
    });
    await plugin.definition.setup(harness.ctx);

    const result = await harness.executeTool("nexus_recall", { query: "paperclip memory" }, runCtx);

    expect(result.error).toBeUndefined();
    expect(result.content).toContain("Remember to use Nexus");
    expect(fetchMock).toHaveBeenCalledWith("http://nexus.test/v1/memory/recall", expect.objectContaining({ method: "POST" }));
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    const body = JSON.parse(String(init?.body));
    expect(body.agent_id).toBe("agent-1");
    expect(body.limit).toBe(3);
  });

  it("saves Paperclip context to Nexus with provenance tags", async () => {
    const fetchMock = mockFetchJson({ id: "memory-1" });
    const harness = createTestHarness({ manifest, config: { nexusUrl: "http://nexus.test", nexusSecret: "secret" } });
    await plugin.definition.setup(harness.ctx);

    const result = await harness.executeTool("nexus_save", {
      content: "LOC-123 decision: use Nexus memory",
      kind: "decision",
      importance: 9,
      tags: ["loc-123"],
      issueId: "issue-1",
    }, runCtx);

    expect(result.error).toBeUndefined();
    expect(result.content).toBe("Memory saved to Nexus.");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    const body = JSON.parse(String(init?.body));
    expect(body.memory_type).toBe("observation");
    expect(body.importance).toBe(0.9);
    expect(body.tags).toEqual(expect.arrayContaining(["paperclip", "decision", "company:company-1", "project:project-1", "issue:issue-1", "run:run-1", "loc-123"]));
    expect(body.metadata.paperclip).toBe(true);
    expect(harness.activity[0]?.message).toBe("Saved Paperclip memory to Nexus");
  });

  it("checks Nexus status", async () => {
    mockFetchJson({ healthy: true, version: "1.0.0" });
    const harness = createTestHarness({ manifest, config: { nexusUrl: "http://nexus.test", nexusSecret: "secret" } });
    await plugin.definition.setup(harness.ctx);

    const result = await harness.executeTool("nexus_status", {}, runCtx);
    expect(result.error).toBeUndefined();
    expect(result.content).toContain("Nexus reachable");
  });
});
