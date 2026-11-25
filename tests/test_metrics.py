"""Testes da agregação de métricas reais."""

from __future__ import annotations

import pytest

from ddoslab.metrics import MetricsStore


def test_agrega_resultados_e_latencias_por_papel():
    metricas = MetricsStore()
    metricas.record_response("virtual-01", "virtual", "sucesso", 100.0)
    metricas.record_response("virtual-01", "virtual", "sucesso", 200.0)
    metricas.record_response("virtual-01", "virtual", "rejeitado", 1.0)
    metricas.record_response("sonda-legitima", "legitimo", "sucesso", 50.0)
    metricas.record_response(
        "sonda-legitima", "legitimo", "falha_capacidade", 2.0
    )
    metricas.record_transport_failure("virtual-02", "virtual", 300.0)

    snapshot = metricas.snapshot()
    total = snapshot["total"]

    assert total["total"] == 6
    assert total["sucesso"] == 3
    assert total["rejeitado"] == 1
    assert total["falha_capacidade"] == 1
    assert total["falha_transporte"] == 1
    assert total["falhas_disponibilidade"] == 2
    assert total["taxa_sucesso"] == pytest.approx(50.0)
    assert total["latencia_p50_ms"] == pytest.approx(100.0)
    assert total["latencia_p95_ms"] == pytest.approx(200.0)

    legitimo = snapshot["por_papel"]["legitimo"]
    assert legitimo["total"] == 2
    assert legitimo["taxa_sucesso"] == pytest.approx(50.0)
    assert snapshot["por_papel"]["virtual"]["total"] == 4


def test_serie_temporal_tem_janela_de_sessenta_segundos():
    metricas = MetricsStore()
    metricas.record_response("navegador", "legitimo", "sucesso", 12.5)

    serie = metricas.snapshot()["serie_temporal"]

    assert len(serie) == 60
    assert serie[-1]["segundo"] > serie[0]["segundo"]
    assert serie[-1]["sucesso"] == 1
    assert serie[-1]["latencia_media_ms"] == pytest.approx(12.5)


def test_snapshot_por_cliente_e_isolado():
    metricas = MetricsStore()
    metricas.record_response("a", "virtual", "sucesso", 10.0)
    metricas.record_response("a", "virtual", "rejeitado", 1.0)
    metricas.record_response("b", "legitimo", "sucesso", 20.0)

    cliente = metricas.client_snapshot("a")

    assert cliente is not None
    assert cliente["total"] == 2
    assert cliente["sucesso"] == 1
    assert cliente["rejeitado"] == 1
    assert cliente["latencia_p95_ms"] == pytest.approx(10.0)
    assert metricas.client_snapshot("inexistente") is None


def test_reset_descarta_metricas():
    metricas = MetricsStore()
    metricas.record_response("a", "virtual", "sucesso", 10.0)
    metricas.reset()

    snapshot = metricas.snapshot()
    assert snapshot["total"]["total"] == 0
    assert snapshot["por_cliente"] == []


def test_resultado_invalido_e_recusado():
    metricas = MetricsStore()
    with pytest.raises(ValueError):
        metricas.record_response("a", "virtual", "desconhecido", 10.0)


def test_janela_congela_na_ultima_amostra(monkeypatch):
    relogio = {"agora": 1000.0}
    monkeypatch.setattr("ddoslab.metrics.time.time", lambda: relogio["agora"])
    metricas = MetricsStore(timeline_seconds=3)
    metricas.record_response("a", "virtual", "sucesso", 15.0)

    relogio["agora"] = 1010.0
    snapshot = metricas.snapshot()

    assert snapshot["janela_ao_vivo"] is False
    assert snapshot["janela_fim_segundo"] == 1000
    assert snapshot["serie_temporal"][-1]["sucesso"] == 1
