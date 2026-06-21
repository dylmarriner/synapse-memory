#!/usr/bin/env node

/**
 * Install Nexus Memory into IDE MCP configs.
 *
 * Usage:
 *   node install-to-ides.mjs
 *   node install-to-ides.mjs --windsurf --antigravity --vscode
 *
 * Adds the "nexus" MCP server to:
 *   Windsurf:     ~/.codeium/windsurf/mcp_config.json
 *   Antigravity:  ~/.gemini/antigravity/mcp_config.json
 *   VS Code:      ~/.vscode/mcp.json
 */

import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const NEXUS_URL = process.env.NEXUS_URL || "http://100.93.75.87:7777";

const NEXUS_MCP_CONFIG = {
  url: `${NEXUS_URL}/mcp`,
  headers: {
    Authorization: "Bearer ${NEXUS_SECRET}",
  },
};

const IDES = [
  {
    id: "windsurf",
    label: "Windsurf IDE",
    configPath: path.join(os.homedir(), ".codeium", "windsurf", "mcp_config.json"),
    key: "mcpServers",
  },
  {
    id: "antigravity",
    label: "Antigravity IDE",
    configPath: path.join(os.homedir(), ".gemini", "antigravity", "mcp_config.json"),
    key: "mcpServers",
  },
  {
    id: "vscode",
    label: "VS Code",
    configPath: path.join(os.homedir(), ".vscode", "mcp.json"),
    key: "servers",
  },
];

const args = process.argv.slice(2);
const onlyIds = args
  .filter((a) => a.startsWith("--"))
  .map((a) => a.replace("--", ""));

const targets = onlyIds.length
  ? IDES.filter((ide) => onlyIds.includes(ide.id))
  : IDES;

console.log("=== Nexus — IDE MCP Installer ===\n");

for (const ide of targets) {
  const dir = path.dirname(ide.configPath);
  fs.mkdirSync(dir, { recursive: true });

  let config = {};
  try {
    if (fs.existsSync(ide.configPath)) {
      config = JSON.parse(fs.readFileSync(ide.configPath, "utf-8"));
    }
  } catch {
    config = {};
  }

  const mcpServers = config[ide.key] ?? {};

  if (mcpServers["nexus"]) {
    console.log(`  ${ide.label}: nexus already configured, updating...`);
  } else {
    console.log(`  ${ide.label}: adding nexus...`);
  }

  mcpServers["nexus"] = NEXUS_MCP_CONFIG;
  config[ide.key] = mcpServers;

  fs.writeFileSync(ide.configPath, JSON.stringify(config, null, 2) + "\n", "utf-8");
  console.log(`    → ${ide.configPath}`);
}

console.log("\nDone. Restart your IDE to pick up the new MCP server.");
