# Nexus Memory Evals

These lightweight evals exercise roadmap-critical memory behavior against a live
Nexus server.

They cover:

- preference recall after noise
- correction/latest-preference recall
- recurring bug fix recall
- global vs agent-specific recall
- project architecture decision recall
- irrelevant memory suppression smoke checks

## Run

Start Nexus, then run:

```bash
export NEXUS_URL=http://localhost:7777
export NEXUS_SECRET=...
python3 evals/run_memory_evals.py
```

Optional:

```bash
python3 evals/run_memory_evals.py --agent-id eval-$(date +%s) --json
```

The eval harness uses only the REST API and standard library Python.
