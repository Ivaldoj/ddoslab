"""Testes do limitador de taxa por cliente."""

from __future__ import annotations

import pytest

from ddoslab.rate_limit import RateLimiterRegistry, TokenBucket


class RelogioFalso:
    """Relógio monotônico controlável para testes do limitador."""

    def __init__(self, inicial: float = 100.0) -> None:
        self.agora = inicial

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


def test_balde_permite_rajada_e_depois_rejeita():
    relogio = RelogioFalso()
    balde = TokenBucket(2.0, 2, clock=relogio)

    assert balde.consume()[0] is True
    assert balde.consume()[0] is True
    permitido, espera = balde.consume()

    assert permitido is False
    assert espera == pytest.approx(0.5)


def test_balde_recarrega_com_o_tempo():
    relogio = RelogioFalso()
    balde = TokenBucket(2.0, 2, clock=relogio)
    balde.consume()
    balde.consume()
    assert balde.consume()[0] is False

    relogio.avancar(0.5)
    assert balde.consume()[0] is True
    assert balde.consume()[0] is False


def test_limitador_mantem_baldes_independentes():
    relogio = RelogioFalso()
    limitador = RateLimiterRegistry(2.0, 1, clock=relogio)
    limitador.configure(True)

    assert limitador.allow("cliente-a")[0] is True
    assert limitador.allow("cliente-a")[0] is False
    assert limitador.allow("cliente-b")[0] is True
    assert limitador.active_clients() == 2


def test_limitador_desligado_permite_tudo():
    relogio = RelogioFalso()
    limitador = RateLimiterRegistry(1.0, 1, clock=relogio)
    limitador.configure(False)

    for _ in range(20):
        assert limitador.allow("cliente-a")[0] is True
    assert limitador.active_clients() == 0


def test_reconfigurar_limpa_o_estado_dos_baldes():
    relogio = RelogioFalso()
    limitador = RateLimiterRegistry(2.0, 1, clock=relogio)
    limitador.configure(True)
    assert limitador.allow("cliente-a")[0] is True
    assert limitador.allow("cliente-a")[0] is False

    limitador.configure(True)
    assert limitador.allow("cliente-a")[0] is True


def test_rejeicao_traz_retry_after_minimo():
    limitador = RateLimiterRegistry(10.0, 1)
    assert limitador.retry_after_seconds() == 1
