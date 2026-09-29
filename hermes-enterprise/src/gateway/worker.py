"""
Shared async agent worker queue.
Gateways enqueue (context, message_text) → worker runs inference → dispatches reply.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Coroutine, Optional

from src.gateway.mapper import InternalContext


@dataclass
class AgentJob:
    context: InternalContext
    text: str
    reply_fn: Callable[[str], Coroutine]
    attachments: list = None


# Module-level queue — shared across all gateway handlers
_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
_worker_task: Optional[asyncio.Task] = None


def get_queue() -> asyncio.Queue:
    return _queue


async def enqueue(job: AgentJob) -> None:
    await _queue.put(job)


async def _worker_loop():
    from src.models.router import get_router
    from src.models.base import Message

    router = get_router()
    while True:
        try:
            job: AgentJob = await _queue.get()
            try:
                messages = [Message(role="user", content=job.text)]
                full_response = ""
                async for chunk in router.route(messages=messages, model="claude/claude-sonnet-4-6"):
                    full_response += chunk.delta
                if job.reply_fn and full_response.strip():
                    await job.reply_fn(full_response.strip())
            except Exception as e:
                try:
                    await job.reply_fn(f"⚠️ Error: {e}")
                except Exception:
                    pass
            finally:
                _queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(1)


def start_worker():
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop(), name="gateway-worker")


def stop_worker():
    global _worker_task
    if _worker_task:
        _worker_task.cancel()
