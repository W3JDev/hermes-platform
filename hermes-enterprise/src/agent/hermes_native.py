"""
Native Hermes Agent Engine Bridge.
Embeds the official Nous Research Hermes Agent framework (run_agent.AIAgent)
directly into the enterprise platform backend, wiring callbacks into SSE streams.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from src.config import settings

logger = logging.getLogger("hermes.native_agent")

# Ensure the official Hermes Agent package is in the Python search path
if settings.HERMES_AGENT_ROOT not in sys.path:
    sys.path.insert(0, settings.HERMES_AGENT_ROOT)

try:
    from run_agent import AIAgent
    HERMES_FRAMEWORK_AVAILABLE = True
except Exception as exc:
    logger.warning("Failed to import official Hermes AIAgent: %s", exc)
    HERMES_FRAMEWORK_AVAILABLE = False


class NativeHermesAgentEngine:
    """
    Orchestrates the official Nous Research AIAgent instance for multi-tenant enterprise turns.
    Translates model configurations into AIAgent client parameters and streams output via SSE.
    """

    @classmethod
    def is_available(cls) -> bool:
        return HERMES_FRAMEWORK_AVAILABLE

    @classmethod
    def resolve_agent_config(cls, model_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Map enterprise workflow presets to AIAgent initialization arguments.
        """
        norm_model = (model_name or settings.DEFAULT_MODEL).lower()

        # 1. Direct Gemini Provider (if Gemini key configured)
        if ("gemini" in norm_model or "flash" in norm_model or "google" in norm_model) and settings.GEMINI_API_KEY:
            target_model = "gemini-2.5-pro" if "pro" in norm_model else "gemini-2.5-flash"
            return {
                "model": target_model,
                "provider": "gemini",
                "api_key": settings.GEMINI_API_KEY,
            }

        # 2. Sub-second Fast via Groq
        if ("groq" in norm_model or "fast" in norm_model) and settings.GROQ_API_KEY:
            return {
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": settings.GROQ_API_KEY,
                "model": "qwen/qwen3.8-27b",
            }

        # 3. Sprites AI Gateway (Claude Sonnet / GPT-5.5)
        if settings.HERMES_SPRITES_API_KEY and ("sprites" in norm_model or "claude" in norm_model or "gpt" in norm_model):
            target_model = settings.HERMES_LOCAL_DEFAULT_MODEL
            if "pro" in norm_model or "claude" in norm_model:
                target_model = "claude/claude-sonnet-4-6"
            elif "gpt" in norm_model:
                target_model = "gpt-5.5"
            return {
                "base_url": settings.HERMES_SPRITES_BASE_URL,
                "api_key": settings.HERMES_SPRITES_API_KEY,
                "model": target_model,
            }

        # 4. Local Private via Ollama (Default & verified working locally)
        return {
            "base_url": settings.HERMES_OLLAMA_BASE_URL,
            "api_key": "ollama",
            "model": settings.HERMES_OLLAMA_MODEL,
        }

    @classmethod
    async def run_turn_stream(
        cls,
        user_message: str,
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute one conversation turn using AIAgent, streaming text deltas and tool events.
        """
        if not HERMES_FRAMEWORK_AVAILABLE:
            yield {"type": "delta", "delta": "Hermes native framework unavailable. Falling back to router."}
            yield {"type": "done"}
            return

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def stream_delta_cb(delta: Any):
            if delta and isinstance(delta, str):
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "delta", "delta": delta})

        def tool_start_cb(name: str, args: Any = None):
            action_type = "terminal" if ("bash" in name or "powershell" in name or "terminal" in name) else (
                "browser_use" if "browse" in name else "tool"
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "action_start",
                    "action_type": action_type,
                    "tool_name": name,
                    "action_id": str(uuid.uuid4())[:8],
                    "details": args,
                },
            )

        def tool_complete_cb(name: str, result: Any = None):
            action_type = "terminal" if ("bash" in name or "powershell" in name or "terminal" in name) else (
                "browser_use" if "browse" in name else "tool"
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "action_complete",
                    "action_type": action_type,
                    "tool_name": name,
                    "status": "completed",
                    "result": str(result)[:300] if result else None,
                },
            )

        def thinking_cb(thinking_text: str):
            if thinking_text and isinstance(thinking_text, str):
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "thinking", "text": thinking_text})

        cfg = cls.resolve_agent_config(model_name)
        sid = session_id or str(uuid.uuid4())

        def _run_agent_thread():
            try:
                agent = AIAgent(
                    session_id=sid,
                    stream_delta_callback=stream_delta_cb,
                    tool_start_callback=tool_start_cb,
                    tool_complete_callback=tool_complete_cb,
                    thinking_callback=thinking_cb,
                    quiet_mode=True,
                    **cfg,
                )

                res = agent.run_conversation(
                    user_message=user_message,
                    system_message=system_prompt,
                    conversation_history=conversation_history or [],
                    stream_callback=stream_delta_cb,
                )
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "turn_finished", "result": res})
            except Exception as e:
                logger.error("AIAgent run_conversation exception: %s", e)
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "sentinel_done"})

        # Run the official Hermes turn in a background worker thread
        agent_thread_task = asyncio.create_task(asyncio.to_thread(_run_agent_thread))

        has_yielded_delta = False
        fallback_text = None

        while True:
            item = await queue.get()
            if item.get("type") == "sentinel_done":
                break
            if item.get("type") == "turn_finished":
                r = item.get("result")
                if isinstance(r, dict):
                    fallback_text = r.get("response") or r.get("text") or r.get("output")
                elif isinstance(r, str):
                    fallback_text = r
                continue
            if item.get("type") == "delta":
                has_yielded_delta = True
            yield item

        if not has_yielded_delta and fallback_text:
            yield {"type": "delta", "delta": fallback_text}

        await agent_thread_task
        yield {"type": "done"}
