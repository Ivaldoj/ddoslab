"""Testes do controle de capacidade concorrente."""

from __future__ import annotations

import time

from ddoslab.capacity import ServiceCapacity


def test_capacidade_limita_requisicoes_simultaneas():
    capacidade = ServiceCapacity(max_concurrent=1, processing_ms=30)

    assert capacidade.try_acquire() is True
    assert capacidade.active == 1
    assert capacidade.try_acquire() is False
    assert capacidade.active == 1

    capacidade.release()
    assert capacidade.active == 0
    assert capacidade.try_acquire() is True
    capacidade.release()


def test_processamento_respeita_duracao_configurada():
    capacidade = ServiceCapacity(max_concurrent=1, processing_ms=40)
    inicio = time.perf_counter()

    assert capacidade.try_acquire() is True
    try:
        capacidade.process()
    finally:
        capacidade.release()

    decorrido = time.perf_counter() - inicio
    assert decorrido >= 0.035


def test_status_expoe_ocupacao_atual():
    capacidade = ServiceCapacity(max_concurrent=2, processing_ms=10)
    status = capacidade.status()

    assert status["maximo"] == 2
    assert status["ocupadas"] == 0
    assert status["processamento_simulado_ms"] == 10
