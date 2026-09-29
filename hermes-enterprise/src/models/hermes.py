"""
Hermes Local API Adapter — connects to the locally running Hermes Agent at port 9119.
Also exposes the Sprites gateway (ai-gateway-bufxd.sprites.app/v1) as an OpenAI-compat endpoint.
"""
from __future__ import annotations

import base64
import time
from typing import AsyncIterator, List, Optional

from openai import AsyncOpenAI

from src.config import settings
from src.models.base import (
    BaseModelAdapter,
    ContentPart,
    Message,
    ProviderHealthStatus,
    StreamChunk,
    ToolDefinition,
)


def _to_openai_messages(messages: List[Message]) -> List[dict]:
    result = []
    for msg in messages:
        role = msg.role if msg.role in ("user", "assistant", "system", "tool") else "user"
        if isinstance(msg.content, list):
            parts = []
            for item in msg.content:
                if isinstance(item, ContentPart):
                    if item.type == "image":
                        if item.data:
                            b64 = base64.b64encode(item.data).decode("utf-8")
                            mime = item.mime_type or "image/jpeg"
                            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
                        elif item.url:
                            parts.append({"type": "image_url", "image_url": {"url": item.url}})
                        else:
                            parts.append({"type": "text", "text": item.text or ""})
                    elif item.type == "text":
                        parts.append({"type": "text", "text": item.text or ""})
                    else:
                        parts.append({"type": "text", "text": item.text or ""})
                elif isinstance(item, dict):
                    parts.append(item)
                elif isinstance(item, str):
                    parts.append({"type": "text", "text": item})
            result.append({"role": role, "content": parts})
        elif isinstance(msg.content, str):
            result.append({"role": role, "content": msg.content})
        else:
            result.append({"role": role, "content": str(msg.content)})
    return result


def _to_openai_tools(tools: List[ToolDefinition]) -> List[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


class HermesLocalAdapter(BaseModelAdapter):
    """
    Adapter for the locally running Hermes Agent API on port 9119.
    Uses the Sprites gateway with an OpenAI-compatible interface.
    Falls back to direct Ollama on port 11434 if Hermes is unavailable.
    """

    def __init__(self, model_name: str = None, use_sprites: bool = True):
        self.model_name = model_name or settings.HERMES_LOCAL_DEFAULT_MODEL
        self.use_sprites = use_sprites

        if use_sprites and settings.HERMES_SPRITES_API_KEY:
            # Use Sprites gateway — highest quality models (Claude, GPT-5.5 etc.)
            self._client = AsyncOpenAI(
                base_url=settings.HERMES_SPRITES_BASE_URL,
                api_key=settings.HERMES_SPRITES_API_KEY,
            )
        elif settings.HERMES_LOCAL_PORT:
            # Use local Hermes API server directly
            self._client = AsyncOpenAI(
                base_url=f"http://localhost:{settings.HERMES_LOCAL_PORT}/v1",
                api_key=settings.HERMES_LOCAL_API_KEY or "local",
            )
        else:
            # Fallback: Ollama
            self._client = AsyncOpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
            )
            self.model_name = settings.HERMES_OLLAMA_MODEL

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        stream: bool = True,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        kwargs = dict(
            model=self.model_name,
            messages=_to_openai_messages(messages),
            temperature=temperature,
            stream=stream,
        )
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"

        if stream:
            response = await self._client.chat.completions.create(**kwargs)
            async for chunk in response:
                delta = chunk.choices[0].delta.content or "" if chunk.choices else ""
                finish = chunk.choices[0].finish_reason if chunk.choices else None
                yield StreamChunk(delta=delta, finish_reason=finish)
        else:
            response = await self._client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content or ""
            usage = {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }
            yield StreamChunk(delta=text, finish_reason="stop", usage=usage)

    async def get_health(self) -> ProviderHealthStatus:
        start = time.monotonic()
        try:
            models = await self._client.models.list()
            latency = (time.monotonic() - start) * 1000
            model_ids = [m.id for m in models.data[:3]] if models.data else []
            return ProviderHealthStatus(
                provider="hermes_local",
                healthy=True,
                latency_ms=latency,
                error=None,
            )
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return ProviderHealthStatus(
                provider="hermes_local",
                healthy=False,
                latency_ms=latency,
                error=str(e),
            )


class OllamaAdapter(BaseModelAdapter):
    """Direct Ollama adapter for locally running models (port 11434)."""

    def __init__(self, model_name: str = None):
        self.model_name = model_name or settings.HERMES_OLLAMA_MODEL
        self._client = AsyncOpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama",
        )

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        stream: bool = True,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        kwargs = dict(
            model=self.model_name,
            messages=_to_openai_messages(messages),
            temperature=temperature,
            stream=stream,
        )
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)

        if stream:
            response = await self._client.chat.completions.create(**kwargs)
            async for chunk in response:
                delta = chunk.choices[0].delta.content or "" if chunk.choices else ""
                finish = chunk.choices[0].finish_reason if chunk.choices else None
                yield StreamChunk(delta=delta, finish_reason=finish)
        else:
            response = await self._client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content or ""
            yield StreamChunk(delta=text, finish_reason="stop")

    async def get_health(self) -> ProviderHealthStatus:
        start = time.monotonic()
        try:
            await self._client.models.list()
            latency = (time.monotonic() - start) * 1000
            return ProviderHealthStatus(provider="ollama", healthy=True, latency_ms=latency)
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return ProviderHealthStatus(provider="ollama", healthy=False, latency_ms=latency, error=str(e))


class GroqAdapter(BaseModelAdapter):
    """Ultra-fast inference adapter via Groq API."""

    def __init__(self, model_name: str = "qwen/qwen3.8-27b"):
        self.model_name = model_name
        self._client = AsyncOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=settings.GROQ_API_KEY,
        )

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        stream: bool = True,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        kwargs = dict(
            model=self.model_name,
            messages=_to_openai_messages(messages),
            temperature=temperature,
            stream=stream,
        )
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)

        if stream:
            response = await self._client.chat.completions.create(**kwargs)
            async for chunk in response:
                delta = chunk.choices[0].delta.content or "" if chunk.choices else ""
                finish = chunk.choices[0].finish_reason if chunk.choices else None
                yield StreamChunk(delta=delta, finish_reason=finish)
        else:
            response = await self._client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content or ""
            yield StreamChunk(delta=text, finish_reason="stop")

    async def get_health(self) -> ProviderHealthStatus:
        start = time.monotonic()
        try:
            await self._client.models.list()
            latency = (time.monotonic() - start) * 1000
            return ProviderHealthStatus(provider="groq", healthy=True, latency_ms=latency)
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return ProviderHealthStatus(provider="groq", healthy=False, latency_ms=latency, error=str(e))

