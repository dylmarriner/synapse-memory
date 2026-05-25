# Synapse Python SDK

```python
from synapse_sdk import SynapseClient

client = SynapseClient(api_key="syn_...")

# Store
client.store(
    kind="semantic",
    content="Auth uses JWT RS256 with 90-day rotation",
    tags=["auth", "jwt"],
    importance=0.9,
)

# Retrieve
results = client.retrieve("JWT authentication")
for mem in results.get("results", []):
    print(f"  [{mem['score']:.1%}] {mem['content_text'][:60]}")

# Context pack (MVCI)
ctx = client.context(query="deployment certs")
print(f"Tokens saved: {ctx['tokens_saved']}")

# Lifecycle hooks
client.on("memory.store", lambda m: print(f"Stored: {m['memory_id']}"))
```
