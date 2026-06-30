"""Embedding generation — degrades gracefully if no API key is set.
Includes Redis-based cache to avoid redundant API calls."""

import hashlib
import logging
from typing import Optional, List
from app.config import settings

log = logging.getLogger("nexus.embeddings")

_client = None
_redis = None


def _openai():
    global _client
    if _client is None:
        if settings.openai_api_key:
            from openai import AsyncOpenAI
            _client = AsyncOpenAI(api_key=settings.openai_api_key)
        # DeepSeek does not support /v1/embeddings — skip it for embedding client
    return _client


_local_embedder = None


def _get_local_embedder():
    global _local_embedder
    if _local_embedder is None:
        try:
            import os
            os.environ.setdefault('HF_HOME', '/tmp/hf_home')
            os.environ.setdefault('TRANSFORMERS_CACHE', '/tmp/hf_home')
            os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
            os.environ.setdefault('XET_CACHE', '/tmp/xet_cache')
            os.makedirs('/tmp/hf_home', exist_ok=True)
            os.makedirs('/tmp/xet_cache', exist_ok=True)
            from fastembed import TextEmbedding
            _local_embedder = TextEmbedding(
                model_name="BAAI/bge-small-en-v1.5",
                max_length=512,
                cache_dir="/tmp/fe_cache",
            )
            log.info("Local embedder loaded: BAAI/bge-small-en-v1.5")
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


def _cache_key(text: str) -> str:
    """Stable cache key based on full text hash + model."""
    h = hashlib.sha256(text.strip().encode()).hexdigest()
    return f"emb:{settings.embedding_model}:{h}"


async def get_embedding(text: str) -> Optional[List[float]]:
    """Generate a text embedding. Returns None if no provider is configured.
    Caches results in Redis for 24 hours to avoid redundant API calls."""
    cache_key = _cache_key(text)

    # Check Redis cache first
    try:
        r = await _get_redis()
        if r:
            cached = await r.get(cache_key)
            if cached:
                import json
                return json.loads(cached)
    except Exception:
        pass

    # Generate embedding via API or local model
    client = _openai()

    # Skip API embedding if using a local model name (fastembed) — prevents
    # pointless 404s to DeepSeek/OpenAI for models they don't support.
    _LOCAL_EMBEDDING_PREFIXES = ("BAAI/", "sentence-transformers/", "intfloat/", "mixedbread-ai/")
    if client is not None and not settings.embedding_model.startswith(_LOCAL_EMBEDDING_PREFIXES):
        try:
            resp = await client.embeddings.create(
                input=[text.replace("\n", " ")[:8000]],
                model=settings.embedding_model,
            )
            embedding = resp.data[0].embedding

            # Cache in Redis for 24 hours
            try:
                if _redis:
                    import json
                    await _redis.setex(cache_key, 86400, json.dumps(embedding))
            except Exception:
                pass

            return embedding
        except Exception as e:
            log.warning("Embedding API failed: %s - trying local model", e)

    # Local ONNX model (no API key needed)
    embedder = _get_local_embedder()
    if embedder is not None:
        try:
            emb = list(embedder.embed(text.replace("\n", " ")[:8000]))
            result = emb[0].tolist() if hasattr(emb[0], 'tolist') else list(emb[0])
            try:
                if _redis:
                    import json
                    await _redis.setex(cache_key, 86400, json.dumps(result))
            except Exception:
                pass
            return result
        except Exception as e2:
            log.warning("Local embedding also failed: %s", e2)
    return None
