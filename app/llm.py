"""Shared LLM client factory — DeepSeek → OpenAI → Anthropic fallback chain."""

from typing import Optional
from app.config import settings


def get_llm_client():
    """Return an OpenAI-compatible async client for the configured primary LLM.

    Preference order:
    1. Local llama/Ollama when the configured model is the local alias.
    2. DeepSeek when a DeepSeek key exists.
    3. OpenAI when an OpenAI key exists.
    4. Local Ollama as a final fallback when a base URL exists.
    """
    model = (settings.llm_model or "").strip().lower()
    if model == "qwen2.5-3b-instruct":
        return get_ollama_client(base_url=settings.ollama_base_url, model=settings.llm_model)
    if settings.deepseek_api_key:
        from openai import AsyncOpenAI
        return AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
    if settings.openai_api_key or settings.openai_base_url:
        from openai import AsyncOpenAI
        kwargs = {"api_key": settings.openai_api_key or "opencode"}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        return AsyncOpenAI(**kwargs)
    if settings.ollama_base_url:
        return get_ollama_client(base_url=settings.ollama_base_url, model=settings.llm_model)
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
        message = resp.choices[0].message
        content = getattr(message, "content", None) or getattr(message, "reasoning_content", None) or ""
        return content.strip() or None
    except Exception:
        return None
