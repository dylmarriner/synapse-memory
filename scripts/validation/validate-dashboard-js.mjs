#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const url = process.env.NEXUS_DASHBOARD_URL || 'http://127.0.0.1:7777/';
const html = await fetch(url).then(async (r) => {
  if (!r.ok) throw new Error(`Dashboard HTTP ${r.status}`);
  return r.text();
});

const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) throw new Error('No inline dashboard script found');
const script = scriptMatch[1];
const dir = mkdtempSync(join(tmpdir(), 'nexus-dashboard-'));
const file = join(dir, 'dashboard.js');
writeFileSync(file, script);
execFileSync('node', ['--check', file], { stdio: 'inherit' });

const required = [
  'function switchTab',
  'function connectSSE',
  'new EventSource',
  "document.getElementById('live-count').textContent='connected'",
  'id="tab-overview"',
  'id="tab-vault"',
  'id="tab-agents"',
  'id="tab-console"',
];
for (const marker of required) {
  const haystack = marker.startsWith('id=') ? html : script;
  if (!haystack.includes(marker)) {
    throw new Error(`Missing dashboard marker: ${marker}`);
  }
}
console.log(JSON.stringify({ ok: true, url, scriptBytes: script.length }));
