#!/usr/bin/env python3
"""Small HTTP embedding service for a Raspberry Pi or spare LAN box.

Run:
  python3 -m venv .venv
  . .venv/bin/activate
  pip install fastapi uvicorn fastembed
  python scripts/pi-embedding-server.py --host 0.0.0.0 --port 8787

Nexus config:
  EMBEDDING_PROVIDER=http
  EMBEDDING_BASE_URL=http://<pi-host>:8787/embed
  EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
  EMBEDDING_DIMS=384
"""

from __future__ import annotations

import argparse
import os
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


DEFAULT_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
DEFAULT_CACHE_DIR = os.getenv("EMBEDDING_CACHE_DIR", "/tmp/fe_cache")
API_KEY = os.getenv("EMBEDDING_API_KEY", "")

app = FastAPI(title="Nexus Pi Embedding Service", version="1.0.0")
_embedder = None
_model_name = DEFAULT_MODEL


class EmbedRequest(BaseModel):
    texts: List[str] = Field(default_factory=list, min_length=1, max_length=128)
    model: Optional[str] = None


class EmbedResponse(BaseModel):
    model: str
    dim: int
    vectors: List[List[float]]


def _check_auth(authorization: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return
    expected = f"Bearer {API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid embedding service token")


def _get_embedder(model_name: str):
    global _embedder, _model_name
    if _embedder is None or _model_name != model_name:
        from fastembed import TextEmbedding

        os.makedirs(DEFAULT_CACHE_DIR, exist_ok=True)
        _embedder = TextEmbedding(
            model_name=model_name,
            max_length=512,
            cache_dir=DEFAULT_CACHE_DIR,
        )
        _model_name = model_name
    return _embedder


@app.get("/health")
def health():
    return {"ok": True, "model": _model_name}


@app.post("/embed", response_model=EmbedResponse, dependencies=[Depends(_check_auth)])
def embed(req: EmbedRequest):
    model_name = req.model or DEFAULT_MODEL
    cleaned = [(text or "").replace("\n", " ").strip()[:8000] for text in req.texts]
    cleaned = [text for text in cleaned if text]
    if not cleaned:
        raise HTTPException(status_code=400, detail="No non-empty texts supplied")

    embedder = _get_embedder(model_name)
    vectors = []
    for vector in embedder.embed(cleaned):
        vectors.append(vector.tolist() if hasattr(vector, "tolist") else list(vector))

    return EmbedResponse(
        model=model_name,
        dim=len(vectors[0]) if vectors else 0,
        vectors=vectors,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Nexus Pi embedding service")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8787")))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    args = parser.parse_args()

    global _model_name
    _model_name = args.model
    os.environ["EMBEDDING_MODEL"] = args.model
    os.environ["EMBEDDING_CACHE_DIR"] = args.cache_dir

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
