"""Claude 3.5/3.7 Sonnet adapter using the Anthropic SDK."""
from __future__ import annotations

import time
from typing import AsyncIterator, List, Optional

import anthropic

from src.config import settings
from src.models.base import (
    BaseModelAdapter,
    Message,
    ProviderHealthStatus,
    StreamChunk,
    ToolDefinition,
)

SUPPORTED_MODELS = {"claude-3-5-sonnet-20241022", "claude-3-7-sonnet-20250219"}


def _to_anthropic_messages(messages: List[Message]) -> List[dict]:
    result = []
    for msg in messages:
        if msg.role == "system":
            continue
        role = "user" if msg.role in ("user", "tool") else "assistant"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        result.append({"role": role, "content": content})
    return result


def _get_system(messages: List[Message]) -> Optional[str]:
    for msg in messages:
        if msg.role == "system":
            return msg.content if isinstance(msg.content, str) else None
    return None


def _to_anthropic_tools(tools: List[ToolDefinition]) -> List[dict]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters or {"type": "object", "properties": {}}}
        for t in tools
    ]


class ClaudeAdapter(BaseModelAdapter):
    def __init__(self, model_name: str = "claude-3-7-sonnet-20250219"):
        if model_name not in SUPPORTED_MODELS:
            model_name = "claude-3-7-sonnet-20250219"
        self.model_name = model_name
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        stream: bool = True,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        anthropic_msgs = _to_anthropic_messages(messages)
        system = _get_system(messages)
        kwargs = dict(
            model=self.model_name,
            max_tokens=4096,
            temperature=temperature,
            messages=anthropic_msgs,
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)

        if stream:
            with self._client.messages.stream(**kwargs) as stream_ctx:
                for text in stream_ctx.text_stream:
                    yield StreamChunk(delta=text)
                final = stream_ctx.get_final_message()
                usage = {
                    "input_tokens": final.usage.input_tokens,
                    "output_tokens": final.usage.output_tokens,
                }
                yield StreamChunk(delta="", finish_reason="stop", usage=usage)
        else:
            response = self._client.messages.create(**kwargs)
            text = "".join(b.text for b in response.content if hasattr(b, "text"))
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
            yield StreamChunk(delta=text, finish_reason="stop", usage=usage)

    async def get_health(self) -> ProviderHealthStatus:
        start = time.monotonic()
        try:
            self._client.messages.create(
                model=self.model_name,
                max_tokens=5,
                messages=[{"role": "user", "content": "ping"}],
            )
            latency = (time.monotonic() - start) * 1000
            return ProviderHealthStatus(provider=self.model_name, healthy=True, latency_ms=latency)
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return ProviderHealthStatus(provider=self.model_name, healthy=False, latency_ms=latency, error=str(e))
