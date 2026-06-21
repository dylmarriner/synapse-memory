# Devin CLI RTK Instructions

Before launching Devin CLI, source `shell-env.sh` so `rtk` is on PATH and Nexus
credentials are available if you want telemetry capture.

Tell Devin: use `scripts/nexus-rtk` for noisy shell commands (`git`, `ls`, `grep`,
tests, docker/kubectl). Fall back to `rtk` if the wrapper is unavailable. Use
`rtk proxy` or raw commands only when exact output is needed.
