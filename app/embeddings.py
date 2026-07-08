"""Embedding generation with graceful degradation and Redis caching.

Supported providers:
- ``http``: remote embedding microservice, for example a Raspberry Pi running
  ``scripts/pi-embedding-server.py``.
- ``openai``: OpenAI-compatible /v1/embeddings API.
- ``local``: in-process FastEmbed model.
- ``auto``: try HTTP when configured, then OpenAI, then local.
- ``disabled``/``none``/``off``: skip vector embeddings.
"""

import hashlib
import json
import logging
from typing import Any, Optional, List

from app.config import settings

log = logging.getLogger("nexus.embeddings")

_client = None
_redis = None
_local_embedder = None

_LOCAL_EMBEDDING_PREFIXES = ("BAAI/", "sentence-transformers/", "intfloat/", "mixedbread-ai/")
_DISABLED_PROVIDERS = {"disabled", "disable", "none", "off", "false", "0"}


def _provider() -> str:
    return (settings.embedding_provider or "auto").strip().lower()


def _clean_text(text: str) -> str:
    return (text or "").replace("\n", " ").strip()[:8000]


def _cache_key(text: str) -> str:
    """Stable cache key based on text hash + provider config."""
    h = hashlib.sha256(text.strip().encode()).hexdigest()
    provider_fingerprint = "|".join(
        [
            _provider(),
            settings.embedding_model or "",
            settings.local_embedding_model or "",
            settings.embedding_base_url or "",
            str(settings.embedding_dims or 0),
        ]
    )
    cfg = hashlib.sha256(provider_fingerprint.encode()).hexdigest()[:16]
    return f"emb:{cfg}:{h}"


def _openai():
    global _client
    if _client is None and settings.openai_api_key:
        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url.rstrip("/")
        _client = AsyncOpenAI(**kwargs)
    return _client


def _get_local_embedder():
    global _local_embedder
    if _local_embedder is None:
        try:
            import os

            os.environ.setdefault("HF_HOME", "/tmp/hf_home")
            os.environ.setdefault("TRANSFORMERS_CACHE", "/tmp/hf_home")
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            os.environ.setdefault("XET_CACHE", "/tmp/xet_cache")
            os.makedirs("/tmp/hf_home", exist_ok=True)
            os.makedirs("/tmp/xet_cache", exist_ok=True)
            os.makedirs(settings.local_embedding_cache_dir, exist_ok=True)

            from fastembed import TextEmbedding

            _local_embedder = TextEmbedding(
                model_name=settings.local_embedding_model,
                max_length=512,
                cache_dir=settings.local_embedding_cache_dir,
            )
            log.info("Local embedder loaded: %s", settings.local_embedding_model)
        except Exception as e:
            log.warning("Local embedder init failed: %s", e)
    return _local_embedder


async def _get_redis():
    """Lazy Redis connection for embedding cache."""
    global _redis
    if _redis is None:
        try:
            from app.redis_util import make_redis

            _redis = make_redis(socket_connect_timeout=2)
        except Exception:
            pass
    return _redis


async def _read_cache(cache_key: str) -> Optional[List[float]]:
    try:
        r = await _get_redis()
        if r:
            cached = await r.get(cache_key)
            if cached:
                return _validate_embedding(json.loads(cached), "cache")
    except Exception:
        pass
    return None


async def _write_cache(cache_key: str, embedding: List[float]) -> None:
    try:
        r = await _get_redis()
        if r:
            await r.setex(cache_key, 86400, json.dumps(embedding))
    except Exception:
        pass


def _coerce_vector(value: Any) -> Optional[List[float]]:
    if value is None:
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        if not value:
            return None
        if isinstance(value[0], (list, tuple)) or hasattr(value[0], "tolist"):
            return _coerce_vector(value[0])
        try:
            return [float(v) for v in value]
        except Exception:
            return None
    return None


def _extract_vector(payload: Any) -> Optional[List[float]]:
    """Accept Nexus/Pi-style, OpenAI-style, or plain vector JSON payloads."""
    if isinstance(payload, dict):
        for key in ("embedding", "vector"):
            vec = _coerce_vector(payload.get(key))
            if vec:
                return vec
        vectors = payload.get("vectors")
        vec = _coerce_vector(vectors)
        if vec:
            return vec
        data = payload.get("data")
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                return _coerce_vector(first.get("embedding") or first.get("vector"))
            return _coerce_vector(first)
    return _coerce_vector(payload)


def _validate_embedding(embedding: Any, provider: str) -> Optional[List[float]]:
    result = _coerce_vector(embedding)
    if not result:
        return None
    expected = int(settings.embedding_dims or 0)
    if expected > 0 and len(result) != expected:
        log.warning(
            "%s embedding dimension mismatch: got %d, expected %d. "
            "Set EMBEDDING_DIMS to match the provider/model before saving vectors.",
            provider,
            len(result),
            expected,
        )
        return None
    return result


async def _http_embedding(text: str) -> Optional[List[float]]:
    """Generate an embedding through a remote HTTP microservice.

    Generic endpoint contract:
      POST /embed {"texts": ["..."], "model": "..."}
      -> {"vectors": [[...]], "model": "...", "dim": 384}

    OpenAI-compatible endpoints are also accepted when the URL ends with
    /v1/embeddings.
    """
    if not settings.embedding_base_url:
        return None

    import httpx

    endpoint = settings.embedding_base_url.strip().rstrip("/")
    if not endpoint.endswith("/embed") and not endpoint.endswith("/v1/embeddings"):
        endpoint = f"{endpoint}/embed"

    headers = {"Content-Type": "application/json"}
    if settings.embedding_api_key:
        headers["Authorization"] = f"Bearer {settings.embedding_api_key}"

    if endpoint.endswith("/v1/embeddings"):
        payload = {"model": settings.embedding_model, "input": [text]}
        if settings.embedding_dims and settings.embedding_model.startswith("text-embedding-3"):
            payload["dimensions"] = settings.embedding_dims
    else:
        payload = {"texts": [text], "model": settings.embedding_model}

    try:
        async with httpx.AsyncClient(timeout=settings.embedding_timeout_seconds) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            return _validate_embedding(_extract_vector(resp.json()), "http")
    except Exception as e:
        log.warning("HTTP embedding provider failed: %s", e)
        return None


async def _openai_embedding(text: str) -> Optional[List[float]]:
    if settings.embedding_model.startswith(_LOCAL_EMBEDDING_PREFIXES):
        return None

    client = _openai()
    if client is None:
        return None

    try:
        kwargs: dict[str, Any] = {
            "input": [text],
            "model": settings.embedding_model,
        }
        # Keep pgvector dimensions aligned with the configured schema. Without
        # this, text-embedding-3-small defaults to 1536 dims while Nexus defaults
        # to 384, which is a gloriously expensive way to make INSERT fail.
        if settings.embedding_dims and settings.embedding_model.startswith("text-embedding-3"):
            kwargs["dimensions"] = settings.embedding_dims
        resp = await client.embeddings.create(**kwargs)
        return _validate_embedding(resp.data[0].embedding, "openai")
    except Exception as e:
        log.warning("Embedding API failed: %s", e)
        return None


async def _local_embedding(text: str) -> Optional[List[float]]:
    embedder = _get_local_embedder()
    if embedder is None:
        return None
    try:
        emb = list(embedder.embed(text))
        return _validate_embedding(emb[0] if emb else None, "local")
    except Exception as e:
        log.warning("Local embedding failed: %s", e)
        return None


async def get_embedding(text: str) -> Optional[List[float]]:
    """Generate a text embedding.

    Returns None if no configured provider works. Recall still has lexical,
    graph, and temporal modes; vector recall and semantic dedupe simply become
    unavailable until a provider is configured.
    """
    cleaned = _clean_text(text)
    if not cleaned:
        return None

    provider = _provider()
    if provider in _DISABLED_PROVIDERS:
        return None

    cache_key = _cache_key(cleaned)
    cached = await _read_cache(cache_key)
    if cached:
        return cached

    embedding: Optional[List[float]] = None

    if provider == "http":
        embedding = await _http_embedding(cleaned)
    elif provider == "openai":
        embedding = await _openai_embedding(cleaned)
    elif provider == "local":
        embedding = await _local_embedding(cleaned)
    else:
        # Auto mode: the cheap remote Pi service wins when configured; otherwise
        # use OpenAI-compatible embeddings if available, then FastEmbed fallback.
        if settings.embedding_base_url:
            embedding = await _http_embedding(cleaned)
        if embedding is None:
            embedding = await _openai_embedding(cleaned)
        if embedding is None:
            embedding = await _local_embedding(cleaned)

    if embedding:
        await _write_cache(cache_key, embedding)
    return embedding
