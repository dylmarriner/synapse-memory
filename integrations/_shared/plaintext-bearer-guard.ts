/**
 * Plaintext-bearer auth guard — ported from rohitg00/agentmemory.
 *
 * Why this exists: when a memory server is configured with a secret
 * (bearer token) and the base URL is plaintext HTTP to a non-loopback
 * host, the bearer token and memory payloads are observable on the
 * network. This guard warns about that and (optionally) refuses to
 * start.
 *
 * Two opt-in flags:
 *   - silently warn (default) — call sites log a single warning,
 *     never spam
 *   - throw on plaintext bearer (set `NEXUS_REQUIRE_HTTPS=1` or
 *     `AGENTMEMORY_REQUIRE_HTTPS=1`) — for production deploys
 *
 * Loosely inspired by `integrations/openclaw/plugin.mjs` in
 * rohitg00/agentmemory (Apache-2.0). Same algorithm, ported to TS
 * and renamed for Nexus use.
 */

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);

export function normalizedHostname(hostname: string): string {
  return hostname.replace(/^\[|\]$/g, "").toLowerCase();
}

export function usesPlaintextBearerAuth(baseUrl: string, secret: string | undefined | null): boolean {
  if (!secret) return false;
  try {
    const parsed = new URL(baseUrl);
    return parsed.protocol === "http:" && !LOOPBACK_HOSTS.has(normalizedHostname(parsed.hostname));
  } catch {
    return false;
  }
}

export function plaintextBearerAuthMessage(baseUrl: string): string {
  return `Nexus: secret is configured for plaintext HTTP to ${baseUrl}. Bearer tokens and memory payloads can be observed on the network; use HTTPS or an SSH tunnel.`;
}

export interface GuardOptions {
  /** Called once per guard instance the first time a warning fires. */
  warn: (message: string) => void;
  /** Override the env variable that toggles throw-on-plaintext. Default: NEXUS_REQUIRE_HTTPS */
  envFlag?: string;
  /** Read-only env override for testing. */
  env?: Record<string, string | undefined>;
}

export function createPlaintextBearerAuthGuard(opts: GuardOptions): (baseUrl: string, secret: string | undefined | null) => void {
  const env = opts.env ?? process.env;
  const flag = opts.envFlag ?? "NEXUS_REQUIRE_HTTPS";
  let warned = false;

  return function guard(baseUrl: string, secret: string | undefined | null): void {
    if (!usesPlaintextBearerAuth(baseUrl, secret)) return;
    const message = plaintextBearerAuthMessage(baseUrl);
    if (env[flag] === "1") {
      throw new Error(message);
    }
    if (!warned) {
      warned = true;
      opts.warn(message);
    }
  };
}
