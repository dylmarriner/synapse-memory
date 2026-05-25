import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

// ─── Constants ─────────────────────────────────────────────────────

const SYNAPSE_DEFAULT_URL = "http://100.91.55.113:8765/mcp";
const HOST_ADAPTERS: Array<{
  id: string;
  label: string;
  detect(appName: string): boolean;
  configPath: string;
  configKey: string;
}> = [
  {
    id: "vscode",
    label: "VS Code",
    detect: (app) =>
      !app.toLowerCase().includes("windsurf") &&
      !app.toLowerCase().includes("codeium") &&
      !app.toLowerCase().includes("antigravity") &&
      !app.toLowerCase().includes("gemini"),
    configPath: path.join(os.homedir(), ".vscode", "mcp.json"),
    configKey: "servers",
  },
  {
    id: "windsurf",
    label: "Windsurf",
    detect: (app) =>
      app.toLowerCase().includes("windsurf") ||
      app.toLowerCase().includes("codeium"),
    configPath: path.join(os.homedir(), ".codeium", "windsurf", "mcp_config.json"),
    configKey: "mcpServers",
  },
  {
    id: "antigravity",
    label: "Antigravity",
    detect: (app) =>
      app.toLowerCase().includes("antigravity") ||
      app.toLowerCase().includes("gemini"),
    configPath: path.join(os.homedir(), ".gemini", "antigravity", "mcp_config.json"),
    configKey: "mcpServers",
  },
];

// ─── MCP Client ─────────────────────────────────────────────────────

interface Session {
  id: string;
  expiresAt: number;
}

let _session: Session | null = null;

async function ensureSession(url: string): Promise<string> {
  const now = Date.now();
  if (_session && now < _session.expiresAt) return _session.id;

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-03-26",
        capabilities: {},
        clientInfo: { name: "synapse-vscode-extension", version: "0.1.0" },
      },
    }),
  });

  const id = resp.headers.get("mcp-session-id") ?? "";
  if (!id) throw new Error("Failed to get MCP session");
  _session = { id, expiresAt: now + 840_000 };
  return id;
}

async function callServer(
  url: string,
  tool: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const apiKey = vscode.workspace
    .getConfiguration("synapse")
    .get<string>("apiKey", "");

  const sessionId = await ensureSession(url);
  const callArgs = { ...args };
  if (apiKey) callArgs.api_key = apiKey;

  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "Mcp-Session-Id": sessionId,
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name: tool, arguments: callArgs },
    }),
  });

  const data = (await resp.json()) as {
    result?: { content?: Array<{ text: string }> };
    error?: { message: string };
  };

  if (data.error) throw new Error(data.error.message);
  const text = data.result?.content?.[0]?.text;
  if (!text) return { ok: false, error: "Empty response" };
  return JSON.parse(text);
}

function getServerUrl(): string {
  return vscode.workspace
    .getConfiguration("synapse")
    .get<string>("serverUrl", SYNAPSE_DEFAULT_URL);
}

// ─── Host Detection ─────────────────────────────────────────────────

function detectHost(): (typeof HOST_ADAPTERS)[0] | null {
  const appName = vscode.env.appName ?? "";
  for (const adapter of HOST_ADAPTERS) {
    if (adapter.detect(appName)) return adapter;
  }
  return null;
}

function writeMCPConfig(host: (typeof HOST_ADAPTERS)[0]): boolean {
  try {
    const dir = path.dirname(host.configPath);
    fs.mkdirSync(dir, { recursive: true });

    let config: Record<string, unknown> = {};
    if (fs.existsSync(host.configPath)) {
      config = JSON.parse(fs.readFileSync(host.configPath, "utf-8"));
    }

    const mcpServers =
      (config[host.configKey] as Record<string, unknown>) ?? {};

    if (!mcpServers["synapse"]) {
      mcpServers["synapse"] = {
        url: getServerUrl(),
        timeout: 120,
        connect_timeout: 30,
        description:
          "Synapse Enterprise Memory — persistent AI memory backbone",
      };
      config[host.configKey] = mcpServers;
      fs.writeFileSync(host.configPath, JSON.stringify(config, null, 2));
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

// ─── Status Bar ─────────────────────────────────────────────────────

let _statusBarItem: vscode.StatusBarItem | null = null;

function updateStatusBar(connected: boolean) {
  if (!_statusBarItem) return;
  _statusBarItem.text = connected
    ? "$(database) Synapse"
    : "$(circle-slash) Synapse";
  _statusBarItem.tooltip = connected
    ? "Synapse Memory — Connected"
    : "Synapse Memory — Disconnected (click to configure)";
  _statusBarItem.backgroundColor = connected
    ? undefined
    : new vscode.ThemeColor("statusBarItem.warningBackground");
  _statusBarItem.show();
}

// ─── Commands ───────────────────────────────────────────────────────

async function commandHealth() {
  const url = getServerUrl();
  try {
    const result = await callServer(url, "health", {});
    if (result.ok) {
      const lines = [
        `Synapse Memory — Connected`,
        `  Server: ${url}`,
        `  Tailscale: ${result.tailscale_ip ?? "N/A"}`,
        `  Host: ${result.hostname ?? "N/A"}`,
        `  Memories: ${result.memories ?? 0}`,
        `  Tenants: ${result.tenants ?? 0}`,
        `  Version: ${result.version ?? "?"}`,
      ];
      vscode.window.showInformationMessage(lines.join("\n"), {
        modal: false,
      });
      updateStatusBar(true);
    } else {
      vscode.window.showErrorMessage(
        `Synapse: ${result.error ?? "Unknown error"}`,
      );
      updateStatusBar(false);
    }
  } catch (e) {
    vscode.window.showErrorMessage(`Synapse: Cannot reach server — ${e}`);
    updateStatusBar(false);
  }
}

async function commandStore() {
  const content = await vscode.window.showInputBox({
    prompt: "What do you want to remember?",
    placeHolder: "e.g., Auth uses JWT RS256 with 90-day rotation",
    ignoreFocusOut: true,
  });
  if (!content) return;

  const projectKey = await vscode.window.showInputBox({
    prompt: "Project key",
    value: vscode.workspace
      .getConfiguration("synapse")
      .get<string>("defaultProject", "default"),
    ignoreFocusOut: true,
  });

  const kind = await vscode.window.showQuickPick(
    [
      { label: "semantic", description: "Durable knowledge (recommended)" },
      { label: "episodic", description: "Timeline events, incidents" },
      { label: "working", description: "Ephemeral session context" },
    ],
    { placeHolder: "Memory kind", canPickMany: false },
  );

  try {
    const result = await callServer(getServerUrl(), "store", {
      project_key: projectKey ?? "default",
      kind: kind?.label ?? "semantic",
      content,
      source: `vscode:${detectHost()?.id ?? "unknown"}`,
    });
    if (result.ok) {
      vscode.window.showInformationMessage(
        `Memory stored (v${result.version ?? 1})`,
      );
    } else {
      vscode.window.showErrorMessage(
        `Failed: ${result.error ?? "unknown error"}`,
      );
    }
  } catch (e) {
    vscode.window.showErrorMessage(`Error: ${e}`);
  }
}

async function commandRetrieve() {
  const query = await vscode.window.showInputBox({
    prompt: "Search query",
    placeHolder: "e.g., JWT authentication",
    ignoreFocusOut: true,
  });
  if (!query) return;

  const projectKey = vscode.workspace
    .getConfiguration("synapse")
    .get<string>("defaultProject", "default");

  try {
    const result = await callServer(getServerUrl(), "retrieve", {
      query,
      project_key: projectKey ?? "default",
      limit: 10,
    });

    if (result.ok) {
      const items = (result.results ?? []) as Array<{
        score?: number;
        content_text?: string;
        kind?: string;
        tags?: string[];
      }>;

      if (items.length === 0) {
        vscode.window.showInformationMessage("No matching memories found.");
        return;
      }

      const panel = vscode.window.createWebviewPanel(
        "synapseResults",
        `Synapse: "${query}"`,
        vscode.ViewColumn.Two,
        { enableScripts: false },
      );

      const rows = items
        .map(
          (m) => `
        <div class="result">
          <div class="score">${((m.score ?? 0) * 100).toFixed(0)}%</div>
          <div class="kind">${m.kind ?? "?"}</div>
          <div class="content">${escapeHtml(m.content_text ?? "")}</div>
          <div class="tags">${(m.tags ?? []).join(", ")}</div>
        </div>`,
        )
        .join("\n");

      panel.webview.html = `<!DOCTYPE html>
<html>
<head>
<style>
body { font-family: sans-serif; padding: 16px; }
.result { border: 1px solid #ccc; border-radius: 6px; padding: 12px; margin-bottom: 12px; }
.score { font-size: 24px; font-weight: bold; color: var(--vscode-textLink-foreground); }
.kind { font-size: 11px; text-transform: uppercase; color: #888; }
.content { margin: 8px 0; line-height: 1.4; white-space: pre-wrap; }
.tags { font-size: 11px; color: #888; }
</style>
</head>
<body>
<h2>Results for "${escapeHtml(query)}"</h2>
${rows}
</body>
</html>`;
    } else {
      vscode.window.showErrorMessage(
        `Retrieve failed: ${result.error ?? "unknown"}`,
      );
    }
  } catch (e) {
    vscode.window.showErrorMessage(`Error: ${e}`);
  }
}

async function commandContext() {
  const query = await vscode.window.showInputBox({
    prompt: "What are you about to work on?",
    placeHolder: "e.g., fixing authentication middleware",
    ignoreFocusOut: true,
  });
  if (!query) return;

  const projectKey = vscode.workspace
    .getConfiguration("synapse")
    .get<string>("defaultProject", "default");

  try {
    const result = await callServer(getServerUrl(), "context", {
      query,
      project_key: projectKey ?? "default",
      limit: 5,
    });

    if (result.ok) {
      vscode.window.showInformationMessage(
        `Context pack: ${result.count ?? 0} memories, ${result.tokens_saved ?? 0} tokens saved`,
      );
    } else {
      vscode.window.showErrorMessage(
        `Context failed: ${result.error ?? "unknown"}`,
      );
    }
  } catch (e) {
    vscode.window.showErrorMessage(`Error: ${e}`);
  }
}

async function commandConfigure() {
  const url = await vscode.window.showInputBox({
    prompt: "Synapse Server URL",
    value: getServerUrl(),
    ignoreFocusOut: true,
  });
  if (!url) return;

  const config = vscode.workspace.getConfiguration("synapse");
  await config.update("serverUrl", url, vscode.ConfigurationTarget.Global);
  vscode.window.showInformationMessage(`Synapse server set to ${url}`);
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ─── Sidebar Provider ───────────────────────────────────────────────

class SynapseOverviewProvider implements vscode.TreeDataProvider<string> {
  private _onDidChangeTreeData = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  refresh() {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: string): vscode.TreeItem {
    const item = new vscode.TreeItem(element);
    item.contextValue = "synapse-item";
    return item;
  }

  getChildren(): vscode.ProviderResult<string[]> {
    const url = getServerUrl();
    return [
      `Server: ${url}`,
      `Project: ${vscode.workspace.getConfiguration("synapse").get<string>("defaultProject", "default")}`,
      `Auto-sync: ${vscode.workspace.getConfiguration("synapse").get<boolean>("autoSync", true) ? "On" : "Off"}`,
    ];
  }
}

// ─── Activation ─────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext) {
  // Detect host
  const host = detectHost();
  if (host) {
    const wrote = writeMCPConfig(host);
    if (wrote) {
      vscode.window.showInformationMessage(
        `Synapse Memory configured for ${host.label}`,
      );
    }
  }

  // Status bar
  _statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100,
  );
  _statusBarItem.command = "synapse.openDashboard";
  context.subscriptions.push(_statusBarItem);

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand("synapse.store", commandStore),
    vscode.commands.registerCommand("synapse.retrieve", commandRetrieve),
    vscode.commands.registerCommand("synapse.health", commandHealth),
    vscode.commands.registerCommand("synapse.context", commandContext),
    vscode.commands.registerCommand("synapse.configure", commandConfigure),
    vscode.commands.registerCommand("synapse.openDashboard", async () => {
      await vscode.commands.executeCommand(
        "workbench.view.extension.synapse-sidebar",
      );
    }),
  );

  // Register sidebar
  const overviewProvider = new SynapseOverviewProvider();
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider(
      "synapse.overview",
      overviewProvider,
    ),
  );

  // Check health on activate
  commandHealth();

  // File save watcher for auto-sync
  if (vscode.workspace.getConfiguration("synapse").get<boolean>("autoSync", true)) {
    context.subscriptions.push(
      vscode.workspace.onDidSaveTextDocument(async (doc) => {
        if (doc.uri.scheme !== "file") return;
        const content = `Edited: ${path.basename(doc.uri.fsPath)}`;
        try {
          await callServer(getServerUrl(), "store", {
            project_key:
              vscode.workspace
                .getConfiguration("synapse")
                .get<string>("defaultProject", "default"),
            kind: "working",
            content,
            source: `vscode:${host?.id ?? "unknown"}`,
            importance: 0.3,
          });
        } catch {
          // Silent — background sync
        }
      }),
    );
  }

  console.log("Synapse Memory extension activated");
}

export function deactivate() {
  // Cleanup
}
