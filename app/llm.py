"""Shared LLM client factory — DeepSeek → OpenAI → Anthropic fallback chain."""

from typing import Optional
from app.config import settings


def get_llm_client():
    """Return an OpenAI-compatible async client, preferring DeepSeek, then OpenAI.
    Returns None if no API key is configured."""
    if settings.deepseek_api_key:
        from openai import AsyncOpenAI
        return AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
    if settings.openai_api_key:
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=settings.openai_api_key)
    return None


def get_ollama_client(
    base_url: str = "http://localhost:11434/v1",
    model: str = "qwen2.5:0.5b",
) -> "AsyncOpenAI":
    """Return an OpenAI-compatible client pointed at a local Ollama instance.

    No API key needed — Ollama accepts any non-empty string.
    Use this for tiny local models that power the Living Mind.
    """
    from openai import AsyncOpenAI
    return AsyncOpenAI(
        api_key="ollama",  # Ollama doesn't validate keys
        base_url=base_url,
    )


async def llm_complete(
    prompt: str,
    max_tokens: int = 400,
    temperature: float = 0.2,
    model: Optional[str] = None,
) -> Optional[str]:
    """Single-shot LLM completion. Returns None on failure."""
    client = get_llm_client()
    if client is None:
        return None
    try:
        resp = await client.chat.completions.create(
            model=model or settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return None
