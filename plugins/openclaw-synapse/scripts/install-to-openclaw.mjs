#!/usr/bin/env node

/**
 * Install Synapse OpenClaw plugin into an OpenClaw installation.
 *
 * Usage:
 *   node scripts/install-to-openclaw.mjs                     # auto-detect
 *   OPENCLAW_ROOT=/path/to/openclaw node scripts/install-to-openclaw.mjs
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = path.resolve(__dirname, "..");
const OPENCLAW_ROOT = process.env.OPENCLAW_ROOT || findOpenClawRoot();

function findOpenClawRoot() {
  // Check common locations
  const candidates = [
    path.resolve(PLUGIN_ROOT, "..", "..", "openclaw"),
    path.resolve(PLUGIN_ROOT, "..", "openclaw"),
    "/home/lin/openclaw",
    process.cwd(),
  ];
  for (const dir of candidates) {
    const pkg = path.join(dir, "package.json");
    if (fs.existsSync(pkg)) {
      try {
        const data = JSON.parse(fs.readFileSync(pkg, "utf8"));
        if (data.name === "openclaw" || data.openclaw) {
          return dir;
        }
      } catch {
        continue;
      }
    }
  }
  console.error("Could not find OpenClaw installation. Set OPENCLAW_ROOT env var.");
  process.exit(1);
}

const EXTENSIONS_DIR = path.join(OPENCLAW_ROOT, "extensions");
const TARGET_DIR = path.join(EXTENSIONS_DIR, "synapse");
const SOURCE_DIR = PLUGIN_ROOT;

// Files to copy (relative to plugin root)
const FILES_TO_COPY = [
  "package.json",
  "openclaw.plugin.json",
  "tsconfig.json",
  "src/index.ts",
  "src/plugin.ts",
  "src/config.ts",
  "src/tool.ts",
  "src/types.ts",
  "src/prompt-guidance.ts",
  "skills/synapse/SKILL.md",
];

console.log(`Installing Synapse plugin into OpenClaw at: ${OPENCLAW_ROOT}`);
console.log(`Target: ${TARGET_DIR}`);

// Create target directory
fs.mkdirSync(TARGET_DIR, { recursive: true });

// Copy files
for (const file of FILES_TO_COPY) {
  const src = path.join(SOURCE_DIR, file);
  const dst = path.join(TARGET_DIR, file);
  if (fs.existsSync(src)) {
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(src, dst);
    console.log(`  ✓ ${file}`);
  } else {
    console.log(`  - ${file} (not found, skipping)`);
  }
}

// Create api.ts barrel
const apiContent = `export type { SynapseConfig } from "./src/types.js";
export { registerSynapsePlugin, type SynapsePluginApi } from "./src/plugin.js";
`;
fs.writeFileSync(path.join(TARGET_DIR, "api.ts"), apiContent);
console.log("  ✓ api.ts (generated)");

console.log(`\nPlugin installed. Enable it in your OpenClaw config:\n`);
console.log(`  plugins:\n    synapse:\n      enabled: true\n      config:\n        serverUrl: "http://100.91.55.113:8765/mcp"`);
