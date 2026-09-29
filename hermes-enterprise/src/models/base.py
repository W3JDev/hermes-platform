"""
BaseModelAdapter interface and shared data structures for all LLM providers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Literal, Optional


@dataclass
class ContentPart:
    type: Literal["text", "image", "audio", "video"]
    text: Optional[str] = None
    data: Optional[bytes] = None
    mime_type: Optional[str] = None
    url: Optional[str] = None


@dataclass
class Message:
    role: Literal["user", "assistant", "system", "tool"]
    content: str | List[ContentPart]
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass
class StreamChunk:
    delta: str = ""
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage: Optional[Dict[str, int]] = None


@dataclass
class ProviderHealthStatus:
    provider: str
    healthy: bool
    latency_ms: float
    error: Optional[str] = None


class BaseModelAdapter(ABC):
    """Normalized interface every LLM adapter must implement."""

    @abstractmethod
    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        stream: bool = True,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        """Yield StreamChunks as they arrive from the provider."""
        ...

    @abstractmethod
    async def get_health(self) -> ProviderHealthStatus:
        """Return current liveness and latency for circuit breaker probes."""
        ...
