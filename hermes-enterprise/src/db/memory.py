"""
pgvector HNSW + BM25 RRF Hybrid Search Service for Persistent Memory.
Provides async database integration for multi-tenant semantic & lexical memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class MemorySearchResult:
    """Represents a fused semantic and lexical memory retrieval result."""
    memory_id: UUID
    content: str
    metadata: Dict[str, Any]
    scope: str
    created_at: datetime
    rrf_score: float
    vector_rank: Optional[int] = None
    lexical_rank: Optional[int] = None


def compute_rrf_score(
    vector_rank: Optional[int],
    lexical_rank: Optional[int],
    k: int = 60,
    w_vec: float = 0.7,
    w_lex: float = 0.3,
) -> float:
    """
    Computes Reciprocal Rank Fusion score for a document given its rank in vector and lexical lists.
    Formula: score = (w_vec / (k + rank_vec)) + (w_lex / (k + rank_lex))
    """
    score = 0.0
    if vector_rank is not None and vector_rank > 0:
        score += w_vec / (k + vector_rank)
    if lexical_rank is not None and lexical_rank > 0:
        score += w_lex / (k + lexical_rank)
    return score


class MemoryService:
    """Async service managing pgvector HNSW and Full-Text Search with Reciprocal Rank Fusion."""

    def __init__(
        self,
        default_rrf_k: int = 60,
        default_vector_weight: float = 0.7,
        default_lexical_weight: float = 0.3,
        candidate_pool_size: int = 50,
        hnsw_ef_search: int = 64,
    ):
        self.rrf_k = default_rrf_k
        self.vector_weight = default_vector_weight
        self.lexical_weight = default_lexical_weight
        self.candidate_pool_size = candidate_pool_size
        self.hnsw_ef_search = hnsw_ef_search

    async def search_hybrid(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        user_id: UUID,
        query_text: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
        limit: int = 10,
        scope: Optional[str] = None,
        rrf_k: Optional[int] = None,
        w_vec: Optional[float] = None,
        w_lex: Optional[float] = None,
    ) -> List[MemorySearchResult]:
        """
        Executes multi-tenant Reciprocal Rank Fusion combining vector distance and lexical search.
        Guarantees strict tenant and user scope isolation.
        """
        has_text = bool(query_text and query_text.strip())
        has_vec = bool(query_embedding and len(query_embedding) == 768)

        if not has_text and not has_vec:
            return []

        active_k = rrf_k if rrf_k is not None else self.rrf_k
        active_w_vec = w_vec if w_vec is not None else self.vector_weight
        active_w_lex = w_lex if w_lex is not None else self.lexical_weight

        try:
            await session.execute(
                text(f"SET LOCAL hnsw.ef_search = {int(self.hnsw_ef_search)};")
            )
        except Exception:
            pass

        scope_filter = "(m.user_id = :user_id OR m.scope = 'tenant')"
        if scope == "user":
            scope_filter = "m.user_id = :user_id"
        elif scope == "tenant":
            scope_filter = "m.scope = 'tenant'"

        vec_param = f"[{','.join(f'{x:.6f}' for x in query_embedding)}]" if has_vec else None

        sql_query = text(f"""
            WITH vector_search AS (
                SELECT 
                    m.id,
                    ROW_NUMBER() OVER (ORDER BY m.embedding <=> CAST(:query_embedding AS vector)) AS rank_vec
                FROM memory_embeddings m
                WHERE :has_vec
                  AND m.tenant_id = :tenant_id
                  AND {scope_filter}
                ORDER BY m.embedding <=> CAST(:query_embedding AS vector)
                LIMIT :candidate_pool_size
            ),
            lexical_search AS (
                SELECT 
                    m.id,
                    ROW_NUMBER() OVER (ORDER BY ts_rank_cd(m.tsv, websearch_to_tsquery('english', :query_text), 32) DESC) AS rank_lex
                FROM memory_embeddings m
                WHERE :has_text
                  AND m.tenant_id = :tenant_id
                  AND {scope_filter}
                  AND m.tsv @@ websearch_to_tsquery('english', :query_text)
                ORDER BY ts_rank_cd(m.tsv, websearch_to_tsquery('english', :query_text), 32) DESC
                LIMIT :candidate_pool_size
            )
            SELECT 
                m.id AS memory_id,
                m.content,
                m.metadata,
                m.scope,
                m.created_at,
                v.rank_vec,
                l.rank_lex,
                (
                    COALESCE(:w_vec / (:rrf_k + v.rank_vec), 0.0) +
                    COALESCE(:w_lex / (:rrf_k + l.rank_lex), 0.0)
                )::DOUBLE PRECISION AS rrf_score
            FROM memory_embeddings m
            LEFT JOIN vector_search v ON m.id = v.id
            LEFT JOIN lexical_search l ON m.id = l.id
            WHERE v.id IS NOT NULL OR l.id IS NOT NULL
            ORDER BY rrf_score DESC
            LIMIT :limit;
        """)

        result = await session.execute(
            sql_query,
            {
                "has_vec": has_vec,
                "has_text": has_text,
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "query_embedding": vec_param,
                "query_text": query_text or "",
                "candidate_pool_size": self.candidate_pool_size,
                "rrf_k": active_k,
                "w_vec": active_w_vec,
                "w_lex": active_w_lex,
                "limit": limit,
            },
        )

        rows = result.fetchall() if hasattr(result, "fetchall") else []
        if hasattr(rows, "__await__"):
            rows = await rows

        return [
            MemorySearchResult(
                memory_id=row.memory_id,
                content=row.content,
                metadata=row.metadata or {},
                scope=row.scope,
                created_at=row.created_at,
                rrf_score=float(row.rrf_score),
                vector_rank=row.rank_vec,
                lexical_rank=row.rank_lex,
            )
            for row in rows
        ]

    async def add_memory(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        user_id: UUID,
        content: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
        scope: str = "user",
        conversation_id: Optional[UUID] = None,
    ) -> UUID:
        """Inserts a single memory embedding record."""
        if len(embedding) != 768:
            raise ValueError(f"Expected 768-dimensional embedding, got {len(embedding)}")

        vec_param = f"[{','.join(f'{x:.6f}' for x in embedding)}]"
        import json
        stmt = text("""
            INSERT INTO memory_embeddings (
                tenant_id, user_id, conversation_id, scope, content, embedding, metadata
            ) VALUES (
                :tenant_id, :user_id, :conversation_id, :scope, :content, CAST(:embedding AS vector), CAST(:metadata AS jsonb)
            ) RETURNING id;
        """)

        result = await session.execute(
            stmt,
            {
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "conversation_id": str(conversation_id) if conversation_id else None,
                "scope": scope,
                "content": content,
                "embedding": vec_param,
                "metadata": json.dumps(metadata or {}),
            },
        )
        res_id = result.scalar_one()
        if hasattr(res_id, "__await__"):
            res_id = await res_id
        return res_id


default_memory_service = MemoryService()


async def search_hybrid_memories(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    query_text: Optional[str] = None,
    query_embedding: Optional[List[float]] = None,
    limit: int = 10,
    rrf_k: int = 60,
    w_vec: float = 0.7,
    w_lex: float = 0.3,
) -> List[MemorySearchResult]:
    """
    Contract interface for hybrid vector and lexical search with Reciprocal Rank Fusion.
    Satisfies PROJECT.md line 111 interface contract.
    """
    return await default_memory_service.search_hybrid(
        session=session,
        tenant_id=tenant_id,
        user_id=user_id,
        query_text=query_text,
        query_embedding=query_embedding,
        limit=limit,
        rrf_k=rrf_k,
        w_vec=w_vec,
        w_lex=w_lex,
    )
