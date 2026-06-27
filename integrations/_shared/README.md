# Plaintext-Bearer Auth Guard

A security helper, ported from
[rohitg00/agentmemory](https://github.com/rohitg00/agentmemory) (Apache-2.0),
that warns (or optionally throws) when a memory server is configured with a
bearer token over plaintext HTTP to a non-loopback host.

## Why

If you put a bearer token in `NEXUS_SECRET` and your `NEXUS_URL` is
`http://my-server:7777`, the token and every memory payload are sent in
cleartext and can be sniffed on the network. This is fine on
`localhost`/loopback (it never leaves your machine). It is not fine
across a network.

## Usage (TypeScript / OpenClaw plugin)

```ts
import { createPlaintextBearerAuthGuard } from "../integrations/_shared/plaintext-bearer-guard.js";

const guard = createPlaintextBearerAuthGuard({
  warn: (msg) => api.logger.warn?.(msg),
});
guard(cfg.nexusUrl, cfg.nexusSecret);
```

Set `NEXUS_REQUIRE_HTTPS=1` to make it throw instead of warn.

## Usage (Python / installer)

```python
from integrations._shared.plaintext_bearer_guard import check_plaintext_bearer

check_plaintext_bearer(
    base_url=os.environ.get("NEXUS_URL", "http://localhost:7777"),
    secret=os.environ.get("NEXUS_SECRET", ""),
    warn=lambda msg: print(f"[WARN] {msg}", file=sys.stderr),
    env=os.environ,
    flag="NEXUS_REQUIRE_HTTPS",
)
```

## What it checks

| base URL | secret | action |
|---|---|---|
| `http://localhost:7777` | anything | silent (loopback) |
| `https://...` | anything | silent (encrypted) |
| `http://192.168.1.5:7777` | empty | silent (no secret) |
| `http://192.168.1.5:7777` | `abc123` | **warn once**, or throw if `NEXUS_REQUIRE_HTTPS=1` |

## License

Algorithm ported from
[`integrations/openclaw/plugin.mjs`](https://github.com/rohitg00/agentmemory/blob/main/integrations/openclaw/plugin.mjs)
in `rohitg00/agentmemory` (Apache-2.0). See `NOTICE` for attribution.
