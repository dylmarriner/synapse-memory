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
    context_memory_limit: int = 20
    context_memory_char_limit: int = 500
    context_conclusion_limit: int = 8

    cors_origins: str = ""

    learning_interval: int = 300

    reranker_enabled: bool = False
    reranker_provider: str = "none"  # none | llm
    rerank_top_k: int = 30

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


settings = Settings()
