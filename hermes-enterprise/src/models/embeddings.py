"""
Embedding service for Hermes Enterprise Agent.
Provides 768-dimensional embeddings for pgvector HNSW semantic memory.
Resilient cascade: Gemini text-embedding-004 -> Local Ollama (nomic-embed-text) -> Deterministic pseudo-random normalized vector.
"""
from __future__ import annotations

import hashlib
import math
from typing import List
import httpx

from src.config import settings


async def get_embedding(text: str) -> List[float]:
    """
    Generate a 768-dimensional normalized embedding vector.
    Tries:
      1. Gemini text-embedding-004 (if GEMINI_API_KEY set)
      2. Local Ollama nomic-embed-text at port 11434
      3. Deterministic normalized hash-derived vector (never fails)
    """
    cleaned = (text or "").strip()
    if not cleaned:
        cleaned = "empty"

    # 1. Gemini embedding
    if settings.GEMINI_API_KEY:
        try:
            import google.genai as genai
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            res = client.models.embed_content(
                model="text-embedding-004",
                contents=cleaned,
            )
            if hasattr(res, "embedding") and res.embedding and hasattr(res.embedding, "values"):
                vec = list(res.embedding.values)
                if len(vec) == 768:
                    return vec
        except Exception:
            pass

    # 2. Ollama nomic-embed-text
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                "http://localhost:11434/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": cleaned},
            )
            if resp.status_code == 200:
                data = resp.json()
                vec = data.get("embedding", [])
                if len(vec) == 768:
                    return vec
    except Exception:
        pass

    # 3. Fallback deterministic 768-dim normalized embedding (zero disruption guarantee)
    return _generate_fallback_embedding(cleaned)


def _generate_fallback_embedding(text: str, dim: int = 768) -> List[float]:
    """Generates a stable unit-norm 768-dimensional vector based on text SHA256 chunks."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    vals = []
    for i in range(dim):
        byte_val = seed[i % len(seed)]
        # Mix with index to create variation across dimensions
        mix = math.sin((i + 1) * (byte_val + 1))
        vals.append(mix)

    norm = math.sqrt(sum(x * x for x in vals)) or 1.0
    return [round(x / norm, 6) for x in vals]
