"""Capacidade de atendimento intencionalmente limitada do serviço local."""

from __future__ import annotations

import threading
import time


class ServiceCapacity:
    """Controla quantas requisições podem ser processadas ao mesmo tempo.

    O processamento usa uma pausa curta para representar trabalho de CPU/IO.
    Isso mantém a demonstração segura e reproduzível, sem esgotar a máquina.
    """

    def __init__(self, max_concurrent: int, processing_ms: int) -> None:
        if max_concurrent < 1:
            raise ValueError("A concorrência máxima deve ser positiva.")
        if processing_ms < 1:
            raise ValueError("O processamento simulado deve ser positivo.")
        self.max_concurrent = max_concurrent
        self.processing_ms = processing_ms
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._active = 0
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        """Tenta ocupar uma vaga sem enfileirar a requisição."""
        acquired = self._semaphore.acquire(blocking=False)
        if acquired:
            with self._lock:
                self._active += 1
        return acquired

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
        self._semaphore.release()

    def process(self) -> None:
        """Executa o processamento sintético, mantendo a vaga ocupada."""
        time.sleep(self.processing_ms / 1000.0)

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def status(self) -> dict[str, object]:
        return {
            "ocupadas": self.active,
            "maximo": self.max_concurrent,
            "processamento_simulado_ms": self.processing_ms,
        }
