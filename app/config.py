from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    nexus_secret: str = ""
    nexus_port: int = 7777

    database_url: str = "postgresql+asyncpg://nexus:nexuspassword@localhost:5435/nexus"
    redis_url: str = "redis://localhost:6379/0"

    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "deepseek-chat"
    embedding_dims: int = 384

    # Token/cost controls. Defaults favor concise LLM calls while preserving quality.
    llm_cost_saver: bool = True
    llm_input_char_limit: int = 1200
    llm_extract_max_tokens: int = 180
    llm_summary_max_tokens: int = 220
    llm_reflect_max_tokens: int = 300
    llm_synthesis_max_tokens: int = 450
    llm_query_expansion: bool = False
    llm_query_expansion_min_chars: int = 80
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

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


settings = Settings()
