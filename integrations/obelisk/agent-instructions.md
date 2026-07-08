# Obelisk Command Policy

Obelisk is available as the command-output token optimizer. Prefer Obelisk for noisy
shell commands so the model receives compact, relevant output.

If Nexus credentials are configured, prefer the Nexus wrapper so command telemetry
appears in the dashboard:

```bash
scripts/nexus-obelisk git status
scripts/nexus-obelisk git diff
scripts/nexus-obelisk pytest
```

If the wrapper is unavailable, fall back to plain `obelisk`.

Use Obelisk for:

```bash
obelisk run ls .
obelisk run cat path/to/file
obelisk run grep "pattern" .
obelisk run git status
obelisk run git diff
obelisk run git log -n 20
obelisk run pytest
obelisk run npm test
obelisk run pnpm test
obelisk run cargo test
obelisk run go test
obelisk run docker ps
obelisk run kubectl get pods
```

Use raw commands only when exact unfiltered output is required.

Verify Obelisk if needed:

```bash
obelisk --version
obelisk doctor
obelisk stats
```

If `obelisk doctor` fails, the wrong `obelisk` package may be installed.

Obelisk only reduces transient command-output tokens. Durable facts, lessons,
preferences, fixes, and project decisions should still be saved to Nexus memory.
