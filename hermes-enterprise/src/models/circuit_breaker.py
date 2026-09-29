"""3-state Circuit Breaker and global registry for all model providers."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    def __init__(self, provider: str):
        super().__init__(f"Circuit breaker OPEN for provider: {provider}")
        self.provider = provider


@dataclass
class CircuitBreaker:
    provider: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    success_threshold: int = 2

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _opened_at: Optional[float] = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - (self._opened_at or 0) >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
        return self._state

    @property
    def state_str(self) -> str:
        return self.state.value

    async def call(self, coro_fn: Callable[[], Awaitable[Any]]) -> Any:
        async with self._lock:
            current = self.state
            if current == CircuitState.OPEN:
                raise CircuitOpenError(self.provider)

        try:
            result = await coro_fn()
            async with self._lock:
                if self._state == CircuitState.HALF_OPEN:
                    self._success_count += 1
                    if self._success_count >= self.success_threshold:
                        self._state = CircuitState.CLOSED
                        self._failure_count = 0
                elif self._state == CircuitState.CLOSED:
                    self._failure_count = 0
            return result
        except CircuitOpenError:
            raise
        except Exception as exc:
            async with self._lock:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold or self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.OPEN
                    self._opened_at = time.monotonic()
                    self._success_count = 0
            raise


class CircuitBreakerRegistry:
    """Global singleton registry of circuit breakers keyed by provider name."""
    _breakers: Dict[str, CircuitBreaker] = {}

    @classmethod
    def get(cls, provider: str, **kwargs) -> CircuitBreaker:
        if provider not in cls._breakers:
            cls._breakers[provider] = CircuitBreaker(provider=provider, **kwargs)
        return cls._breakers[provider]

    @classmethod
    def all_states(cls) -> Dict[str, str]:
        return {name: cb.state_str for name, cb in cls._breakers.items()}
