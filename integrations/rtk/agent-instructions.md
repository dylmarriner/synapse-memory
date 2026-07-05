# RTK Command Policy

RTK is available as the command-output token optimizer. Prefer RTK for noisy
shell commands so the model receives compact, relevant output.

If Nexus credentials are configured, prefer the Nexus wrapper so command telemetry
appears in the dashboard:

```bash
scripts/nexus-rtk git status
scripts/nexus-rtk git diff
scripts/nexus-rtk pytest
```

If the wrapper is unavailable, fall back to plain `rtk`.

Use RTK for:

```bash
rtk ls .
rtk read path/to/file
rtk grep "pattern" .
rtk git status
rtk git diff
rtk git log -n 20
rtk pytest
rtk npm test
rtk pnpm test
rtk cargo test
rtk go test
rtk docker ps
rtk kubectl get pods
```

Use raw commands or `rtk proxy <command>` only when exact unfiltered output is
required.

Verify RTK if needed:

```bash
rtk --version
rtk gain
```

If `rtk gain` fails, the wrong `rtk` package may be installed.

RTK only reduces transient command-output tokens. Durable facts, lessons,
preferences, fixes, and project decisions should still be saved to Nexus memory.
