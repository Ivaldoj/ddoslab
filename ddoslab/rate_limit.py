"""Limitador de taxa real, por cliente, com algoritmo de balde de fichas."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable


class TokenBucket:
    """Balde de fichas thread-safe com relógio injetável para testes."""

    def __init__(
        self,
        rate_per_second: float,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("A taxa do limitador deve ser positiva.")
        if burst < 1:
            raise ValueError("A rajada do limitador deve ser positiva.")
        self.rate_per_second = float(rate_per_second)
        self.burst = int(burst)
        self._clock = clock
        self._tokens = float(burst)
        self._updated_at = clock()
        self._lock = threading.Lock()

    def consume(self) -> tuple[bool, float]:
        """Tenta consumir uma ficha e devolve (permitido, espera_em_segundos)."""
        with self._lock:
            now = self._clock()
            elapsed = max(0.0, now - self._updated_at)
            self._tokens = min(
                float(self.burst),
                self._tokens + elapsed * self.rate_per_second,
            )
            self._updated_at = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True, 0.0
            missing = 1.0 - self._tokens
            return False, missing / self.rate_per_second


class RateLimiterRegistry:
    """Aplica um balde independente para cada identificador de cliente."""

    def __init__(
        self,
        rate_per_second: float,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rate_per_second = rate_per_second
        self.burst = burst
        self._clock = clock
        self._enabled = False
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def configure(self, enabled: bool) -> None:
        """Liga ou desliga a proteção e descarta o estado anterior dos baldes."""
        with self._lock:
            self._enabled = bool(enabled)
            self._buckets.clear()

    def reset(self, enabled: bool = False) -> None:
        self.configure(enabled)

    def allow(self, client_id: str) -> tuple[bool, float]:
        """Verifica a taxa do cliente; desligado, permite sem consumir fichas."""
        with self._lock:
            enabled = self._enabled
            if not enabled:
                return True, 0.0
            bucket = self._buckets.get(client_id)
            if bucket is None:
                bucket = TokenBucket(
                    self.rate_per_second,
                    self.burst,
                    clock=self._clock,
                )
                self._buckets[client_id] = bucket
        return bucket.consume()

    def retry_after_seconds(self) -> int:
        """Tempo máximo aproximado para uma nova ficha, arredondado para cima."""
        return max(1, math.ceil(1.0 / self.rate_per_second))

    def active_clients(self) -> int:
        with self._lock:
            return len(self._buckets)
