"""Multi-model router with 3-state circuit breaker and automatic cascade failover."""
from __future__ import annotations

from typing import AsyncIterator, List, Literal, Optional

from src.config import settings
from src.models.base import BaseModelAdapter, Message, StreamChunk, ToolDefinition
from src.models.circuit_breaker import CircuitBreakerRegistry, CircuitOpenError
from src.models.gemini import GeminiAdapter
from src.models.claude import ClaudeAdapter


class AllProvidersFailedError(Exception):
    pass


class ModelRouter:
    """
    Routes inference requests across providers with circuit breaker protection.
    Priority cascade: gemini_flash → gemini_pro → claude_sonnet → hermes_vllm
    """

    def __init__(self):
        self._adapters: dict[str, BaseModelAdapter] = {}
        self._init_adapters()

    def _init_adapters(self):
        from src.models.hermes import HermesLocalAdapter, OllamaAdapter, GroqAdapter

        # 1. Direct Gemini API (if key configured)
        if settings.GEMINI_API_KEY:
            try:
                self._adapters["gemini-2.5-flash"] = GeminiAdapter("gemini-2.5-flash")
                self._adapters["gemini-3.8-flash"] = GeminiAdapter("gemini-3.8-flash")
                self._adapters["gemini-2.5-pro"] = GeminiAdapter("gemini-2.5-pro")
            except Exception as e:
                print(f"[Router] Direct Gemini init error: {e}")

        # 2. Ultra-fast Groq inference (Whisper STT & Qwen 3.8)
        if settings.GROQ_API_KEY:
            try:
                self._adapters["groq/qwen3.8-27b"] = GroqAdapter("qwen/qwen3.8-27b")
                self._adapters["groq-fast"] = GroqAdapter("qwen/qwen3.8-27b")
                # If Gemini key isn't provided, wire Gemini aliases to ultra-fast Groq/Claude
                if "gemini-2.5-flash" not in self._adapters:
                    self._adapters["gemini-2.5-flash"] = GroqAdapter("qwen/qwen3.8-27b")
                if "gemini-3.8-flash" not in self._adapters:
                    self._adapters["gemini-3.8-flash"] = GroqAdapter("qwen/qwen3.8-27b")
            except Exception as e:
                print(f"[Router] Groq init error: {e}")

        # 3. Anthropic direct (if key configured)
        if settings.ANTHROPIC_API_KEY:
            self._adapters["claude-3-7-sonnet-20250219"] = ClaudeAdapter("claude-3-7-sonnet-20250219")
            self._adapters["claude-3-5-sonnet-20241022"] = ClaudeAdapter("claude-3-5-sonnet-20241022")

        # 4. Sprites AI Gateway (Claude Sonnet 4.6, GPT-5.5, MiniMax)
        if settings.HERMES_SPRITES_API_KEY:
            try:
                self._adapters["claude/claude-sonnet-4-6"] = HermesLocalAdapter(
                    model_name="claude/claude-sonnet-4-6", use_sprites=True
                )
                self._adapters["gpt-5.5"] = HermesLocalAdapter(
                    model_name="gpt-5.5", use_sprites=True
                )
                self._adapters["MiniMax-M2.7-highspeed"] = HermesLocalAdapter(
                    model_name="MiniMax-M2.7-highspeed", use_sprites=True
                )
                self._adapters["nous-hermes-3"] = HermesLocalAdapter(
                    model_name="claude/claude-sonnet-4-6", use_sprites=True
                )
                if "gemini-2.5-pro" not in self._adapters:
                    self._adapters["gemini-2.5-pro"] = self._adapters["claude/claude-sonnet-4-6"]
            except Exception as e:
                print(f"[Router] Sprites gateway error: {e}")

        # 5. Local Ollama (port 11434)
        try:
            self._adapters["ollama"] = OllamaAdapter()
            self._adapters[settings.HERMES_OLLAMA_MODEL] = OllamaAdapter()
        except Exception as e:
            print(f"[Router] Ollama init skipped: {e}")

        # 6. Fallback ensure Gemini names always resolve
        if "gemini-2.5-flash" not in self._adapters and "ollama" in self._adapters:
            self._adapters["gemini-2.5-flash"] = self._adapters["ollama"]

        # 7. Wire exact R1 preset workflow aliases
        for alias, target in [
            ("gemini/gemini-2.5-flash", "gemini-2.5-flash"),
            ("gemini/gemini-2.5-pro", "gemini-2.5-pro"),
            ("gemini/gemini-3.8-flash", "gemini-3.8-flash"),
            ("hermes/hermes-3-llama-3.1-8b", settings.HERMES_OLLAMA_MODEL),
            ("Balanced Multimodal", "gemini/gemini-2.5-flash"),
            ("Deep Reasoning", "gemini/gemini-2.5-pro"),
            ("Sub-second Fast", "gemini/gemini-3.8-flash"),
            ("Local Private", "hermes/hermes-3-llama-3.1-8b"),
        ]:
            if target in self._adapters:
                self._adapters[alias] = self._adapters[target]
            elif "gemini-2.5-pro" in self._adapters and "pro" in alias.lower():
                self._adapters[alias] = self._adapters["gemini-2.5-pro"]
            elif "gemini-2.5-flash" in self._adapters:
                self._adapters[alias] = self._adapters["gemini-2.5-flash"]

    def _cascade(self, requested: str) -> List[str]:
        """Return ordered list of providers to try, starting with requested."""
        # Workflow presets
        presets = {
            "Balanced Multimodal": "gemini/gemini-2.5-flash",
            "Deep Reasoning": "gemini/gemini-2.5-pro",
            "Sub-second Fast": "gemini/gemini-3.8-flash",
            "Local Private": "hermes/hermes-3-llama-3.1-8b",
            "workflow:balanced": "gemini/gemini-2.5-flash",
            "workflow:deep_reasoning": "gemini/gemini-2.5-pro",
            "workflow:fast_speed": "gemini/gemini-3.8-flash",
            "workflow:offline_local": "hermes/hermes-3-llama-3.1-8b",
        }
        target = presets.get(requested, requested)

        all_providers = [
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.5-pro",
            "gemini/gemini-3.8-flash",
            "hermes/hermes-3-llama-3.1-8b",
            "gemini-2.5-flash",
            "gemini-3.8-flash",
            "gemini-2.5-pro",
            "groq/qwen3.8-27b",
            "groq-fast",
            "claude-3-7-sonnet-20250219",
            "claude/claude-sonnet-4-6",
            "gpt-5.5",
            "MiniMax-M2.7-highspeed",
            "nous-hermes-3",
            "ollama",
            settings.HERMES_OLLAMA_MODEL,
        ]
        order = [target] + [p for p in all_providers if p != target]
        return [p for p in order if p in self._adapters]

    async def route(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        tools: Optional[List[ToolDefinition]] = None,
        stream: bool = True,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        requested = model or settings.DEFAULT_MODEL
        cascade = self._cascade(requested)
        last_error = None

        for provider_name in cascade:
            cb = CircuitBreakerRegistry.get(provider_name)
            if cb.state_str == "OPEN":
                continue
            adapter = self._adapters[provider_name]
            try:
                collected_chunks: List[StreamChunk] = []

                async def _run():
                    chunks = []
                    async for chunk in adapter.generate(messages, tools=tools, stream=stream, temperature=temperature):
                        chunks.append(chunk)
                    return chunks

                chunks = await cb.call(_run)
                for chunk in chunks:
                    yield chunk
                return
            except CircuitOpenError:
                continue
            except Exception as e:
                last_error = e
                continue

        raise AllProvidersFailedError(
            f"All providers failed. Last error: {last_error}"
        )

    def circuit_states(self) -> dict:
        return CircuitBreakerRegistry.all_states()


# Module-level singleton
_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
