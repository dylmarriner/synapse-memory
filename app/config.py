from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    nexus_secret: str = ""
    environment: str = "production"
    # Only honored when environment == "development" — see _verify_key in app/main.py.
    nexus_disable_auth: bool = False
    # Optional separate credential for the web dashboard, so operators can
    # log into the UI without handing out the agent-facing NEXUS_SECRET.
    # Accepted by _verify_key in addition to nexus_secret when set.
    dashboard_password: str = ""
    nexus_port: int = 7777

    database_url: str = "postgresql+asyncpg://nexus:nexuspassword@localhost:5435/nexus"
    redis_url: str = "redis://localhost:6379/0"

    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "deepseek-chat"
    embedding_dims: int = 384

    # Living Mind reasoning models.  The mind reasons with a local Ollama model
    # (fast, on-GPU, no API cost) and falls back to a DeepSeek model when the
    # local call fails or returns nothing.
    mind_llm_model: str = "qwen2.5-3b-instruct"
    mind_fallback_model: str = "deepseek-chat"
    ollama_base_url: str = "http://172.20.0.1:11434/v1"

    # Multi-step LLM pipeline (PR #10).  Each setting enables one
    # capability of the new LLM-driven pipeline.  Disable any of these
    # to fall back to deterministic behaviour for that step.
    mind_enable_extract: bool = True            # pre-extract relevant claims before reason
    mind_enable_verify: bool = True             # verify the draft answer at DEEP depth
    mind_enable_llm_proactive: bool = True      # LLM-driven proactive surfacing
    mind_enable_llm_opinion: bool = True        # LLM-driven opinion formation
    mind_enable_related_graph: bool = True      # expand context with graph-related memories

    # Global mind self-reflection loop (background, unprompted).  A single
    # well-known mind (mind_reflection_mind_id) is kept resident in-process
    # and periodically reflects on recently-saved memories, forming/updating
    # opinions.  Proactive pushes only fire when a reflection crosses the
    # novelty/confidence threshold below, so the push stream stays quiet
    # unless something is actually notable.
    mind_reflection_enabled: bool = True
    mind_reflection_mind_id: str = "nexus"
    mind_reflection_interval_seconds: int = 1800
    mind_reflection_lookback_memories: int = 50
    mind_reflection_max_topics_per_cycle: int = 5
    mind_reflection_push_stance_delta: float = 0.3   # push if strength moves at least this much
    mind_reflection_push_min_strength: float = 0.75  # or push if a strong new opinion crosses this bar
    mind_learning_interval_seconds: int = 3600

    # Token/cost controls. Defaults favor concise LLM calls while preserving quality.
    llm_cost_saver: bool = True
    llm_input_char_limit: int = 1200
    llm_extract_max_tokens: int = 180
    llm_summary_max_tokens: int = 220
    llm_reflect_max_tokens: int = 300
    llm_synthesis_max_tokens: int = 450
    llm_query_expansion: bool = False
    llm_query_expansion_min_chars: int = 80
    llm_memory_organizer_enabled: bool = True
    llm_memory_organizer_similarity_threshold: float = 0.72
    llm_memory_organizer_pair_limit: int = 200
    llm_memory_organizer_max_cluster_size: int = 6
    llm_memory_decompose_enabled: bool = True
    llm_memory_decompose_length_threshold: int = 600
    llm_memory_decompose_batch_limit: int = 10
    context_memory_limit: int = 10
    context_memory_char_limit: int = 200
    context_conclusion_limit: int = 5

    cors_origins: str = ""

    learning_interval: int = 300

    reranker_enabled: bool = False
    reranker_provider: str = "none"  # none | llm | local
    rerank_top_k: int = 30
    reranker_local_model: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"
    reranker_batch_size: int = 16

    confidence_decay_rate: float = 0.95
    confidence_decay_interval_days: int = 7
    confidence_floor: float = 0.1

    # Recall honesty gate — server-side default min relevance (0 = off; callers can override).
    recall_min_relevance: float = 0.0

    # Volatility / shelf-life — auto-expire ephemeral facts so stale info never resurfaces.
    volatility_enabled: bool = True
    volatility_ephemeral_days: int = 3      # "currently", "today", "right now" → short TTL
    volatility_shortterm_days: int = 30     # "this week", "working on" → medium TTL

    # TTL pruning — hard-delete genuinely dead memories (opt-in; deletes data).
    prune_enabled: bool = False
    prune_importance_floor: float = 0.12
    prune_stale_days: int = 60

    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4318/v1/traces"

    allow_agent_export: bool = True
    allow_agent_forget: bool = True

    # ── Embedded / zero-friction install mode ─────────────────────────
    # When true, SQLite and in-process fakeredis replace external Postgres
    # and Redis, and the extraction worker runs inside the API process.
    embedded_mode: bool = False

    # ── Federation / multi-node P2P sync ──────────────────────────────
    federation_enabled: bool = False
    # Comma-separated peer base URLs, e.g. "http://node-b:7777,http://node-c:7777"
    federation_peers: str = ""
    # Shared secret used to HMAC-sign federation payloads between peers.
    federation_secret: str = ""
    # Stable identity for this node (falls back to hostname when empty).
    federation_node_id: str = ""
    # How often the background task pulls from each peer.
    federation_interval_seconds: int = 30
    # Max memories transferred per pull/push batch.
    federation_batch_size: int = 200

    @property
    def federation_peer_list(self) -> list[str]:
        return [p.strip().rstrip("/") for p in self.federation_peers.split(",") if p.strip()]

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


settings = Settings()
