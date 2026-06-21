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

    cors_origins: str = ""

    learning_interval: int = 300

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


settings = Settings()
