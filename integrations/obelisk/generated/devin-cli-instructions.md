# Devin CLI Obelisk Instructions

Before launching Devin CLI, source `shell-env.sh` so `obelisk` is on PATH and Nexus
credentials are available if you want telemetry capture.

Tell Devin: use `scripts/nexus-obelisk` for noisy shell commands (`git`, `ls`, `grep`,
tests, docker/kubectl). Fall back to `obelisk run` if the wrapper is unavailable.
Use raw commands only when exact output is needed.
