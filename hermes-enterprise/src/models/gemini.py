"""Gemini 2.5/3.8 Flash & Pro adapter with full multimodal support."""
from __future__ import annotations

import time
from typing import AsyncIterator, List, Optional

import google.genai as genai
from google.genai import types as gtypes

from src.config import settings
from src.models.base import (
    BaseModelAdapter,
    ContentPart,
    Message,
    ProviderHealthStatus,
    StreamChunk,
    ToolDefinition,
)

SUPPORTED_MODELS = {
    "gemini-2.5-flash",
    "gemini-3.8-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
}


def _to_genai_part(part: ContentPart) -> gtypes.Part:
    if part.type == "text":
        return gtypes.Part.from_text(part.text or "")
    elif part.type == "image" and part.data:
        return gtypes.Part.from_bytes(data=part.data, mime_type=part.mime_type or "image/jpeg")
    elif part.type == "audio" and part.data:
        return gtypes.Part.from_bytes(data=part.data, mime_type=part.mime_type or "audio/wav")
    elif part.type == "video" and part.url:
        return gtypes.Part.from_uri(uri=part.url, mime_type=part.mime_type or "video/mp4")
    return gtypes.Part.from_text(str(part))


def _to_genai_contents(messages: List[Message]) -> List[gtypes.Content]:
    contents = []
    for msg in messages:
        if msg.role == "system":
            continue  # system prompt handled separately
        role = "user" if msg.role in ("user", "tool") else "model"
        if isinstance(msg.content, str):
            parts = [gtypes.Part.from_text(msg.content)]
        else:
            parts = [_to_genai_part(p) for p in msg.content]
        contents.append(gtypes.Content(role=role, parts=parts))
    return contents


def _system_instruction(messages: List[Message]) -> Optional[str]:
    for msg in messages:
        if msg.role == "system":
            return msg.content if isinstance(msg.content, str) else None
    return None


def _to_function_declarations(tools: List[ToolDefinition]) -> List[gtypes.FunctionDeclaration]:
    return [
        gtypes.FunctionDeclaration(
            name=t.name,
            description=t.description,
            parameters=gtypes.Schema(**t.parameters) if t.parameters else None,
        )
        for t in tools
    ]


class GeminiAdapter(BaseModelAdapter):
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        if model_name not in SUPPORTED_MODELS:
            model_name = "gemini-2.5-flash"
        self.model_name = model_name
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        stream: bool = True,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        contents = _to_genai_contents(messages)
        system_inst = _system_instruction(messages)

        config = gtypes.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_inst,
            tools=[gtypes.Tool(function_declarations=_to_function_declarations(tools))] if tools else None,
        )

        if stream:
            response = self._client.models.generate_content_stream(
                model=self.model_name,
                contents=contents,
                config=config,
            )
            for chunk in response:
                delta = ""
                if chunk.candidates:
                    for part in chunk.candidates[0].content.parts:
                        if hasattr(part, "text") and part.text:
                            delta += part.text
                usage = None
                if chunk.usage_metadata:
                    usage = {
                        "input_tokens": chunk.usage_metadata.prompt_token_count or 0,
                        "output_tokens": chunk.usage_metadata.candidates_token_count or 0,
                    }
                yield StreamChunk(delta=delta, usage=usage)
        else:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
            text = response.text or ""
            usage = None
            if response.usage_metadata:
                usage = {
                    "input_tokens": response.usage_metadata.prompt_token_count or 0,
                    "output_tokens": response.usage_metadata.candidates_token_count or 0,
                }
            yield StreamChunk(delta=text, finish_reason="stop", usage=usage)

    async def get_health(self) -> ProviderHealthStatus:
        start = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=[gtypes.Content(role="user", parts=[gtypes.Part.from_text("ping")])],
                config=gtypes.GenerateContentConfig(max_output_tokens=5),
            )
            latency = (time.monotonic() - start) * 1000
            return ProviderHealthStatus(provider=self.model_name, healthy=True, latency_ms=latency)
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return ProviderHealthStatus(provider=self.model_name, healthy=False, latency_ms=latency, error=str(e))
