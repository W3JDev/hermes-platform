"""
Continuous Learning Memory Engine for Hermes Enterprise Agent.
Automatically indexes conversation turns into pgvector HNSW memory and injects
retrieved context into system instructions so Hermes never forgets.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.memory import default_memory_service, MemorySearchResult
from src.db.models import MemoryEmbedding
from src.models.embeddings import get_embedding

logger = logging.getLogger("hermes.memory_auto")


async def learn_from_interaction(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    user_text: str,
    assistant_text: str,
    conversation_id: Optional[UUID] = None,
) -> Optional[UUID]:
    """
    Extracts facts, preferences, or notes from a turn and stores them into persistent pgvector memory.
    """
    user_text = (user_text or "").strip()
    if len(user_text) < 5:
        return None

    # Don't learn transient conversational filler
    filler = {"hello", "hi", "hey", "thanks", "thank you", "ok", "bye", "good morning"}
    if user_text.lower() in filler:
        return None

    # Memory content captures user input and key contextual essence
    memory_content = f"User said: {user_text}"
    if assistant_text and len(assistant_text) > 20:
        first_sentence = assistant_text.split(".")[0].strip()
        if first_sentence:
            memory_content += f" | Context: {first_sentence}"

    try:
        embedding = await get_embedding(memory_content)
        mem_id = await default_memory_service.add_memory(
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            content=memory_content,
            embedding=embedding,
            metadata={"source": "auto_conversation", "conversation_id": str(conversation_id) if conversation_id else None},
            scope="user",
            conversation_id=conversation_id,
        )
        return mem_id
    except Exception as e:
        logger.warning(f"Failed to auto-store memory: {e}")
        return None


async def recall_relevant_memories(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    query_text: str,
    limit: int = 5,
) -> str:
    """
    Retrieves relevant memories using pgvector HNSW and lexical search, returning
    a formatted prompt block to inject into the agent's context.
    """
    if not query_text or len(query_text.strip()) < 3:
        return ""

    try:
        embedding = await get_embedding(query_text)
        results: List[MemorySearchResult] = await default_memory_service.search_hybrid(
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            query_text=query_text,
            query_embedding=embedding,
            limit=limit,
        )

        if not results:
            return ""

        memory_lines = [f"- {r.content}" for r in results if r.content]
        if not memory_lines:
            return ""

        block = (
            "\n[LONG-TERM PERSISTENT MEMORIES - CONTINUOUS LEARNING CONTEXT]\n"
            + "\n".join(memory_lines)
            + "\nUse these remembered user facts and context naturally when answering.\n"
        )
        return block
    except Exception as e:
        logger.warning(f"Failed to recall memories: {e}")
        return ""
