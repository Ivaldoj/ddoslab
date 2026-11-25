"""Teste de integração com servidor HTTP real em loopback."""

from __future__ import annotations

import dataclasses
import json
import socket
import threading
import time
import urllib.error
import urllib.request

from werkzeug.serving import make_server

from ddoslab import create_app
from ddoslab.config import Scenario, Settings


def _porta_livre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soquete:
        soquete.bind(("127.0.0.1", 0))
        return int(soquete.getsockname()[1])


def _requisicao(base: str, caminho: str, payload=None):
    dados = None
    cabecalhos = {"Accept": "application/json"}
    metodo = "GET"
    if payload is not None:
        dados = json.dumps(payload).encode("utf-8")
        cabecalhos["Content-Type"] = "application/json"
        metodo = "POST"
    requisicao = urllib.request.Request(
        base + caminho,
        data=dados,
        method=metodo,
        headers=cabecalhos,
    )
    with urllib.request.urlopen(requisicao, timeout=8) as resposta:
        return resposta.status, json.loads(resposta.read())


def _aguardar_fim(base: str, limite_s: float = 9.0) -> dict:
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim:
        _, estado = _requisicao(base, "/api/estado")
        if estado["experimento"]["estado"] != "executando":
            return estado
        time.sleep(0.2)
    raise AssertionError("O experimento não terminou dentro do tempo esperado.")


def test_execucao_real_comparacao_e_metricas():
    porta = _porta_livre()
    cenario = Scenario(
        key="teste",
        label="Teste controlado",
        description="Cenário curto usado apenas pela suíte automatizada.",
        clients=3,
        rate_per_client=8,
        duration_s=3,
    )
    settings = dataclasses.replace(
        Settings(),
        port=porta,
        max_concurrent=1,
        processing_ms=70,
        rate_limit_per_second=2.0,
        rate_limit_burst=1,
        legit_probe_interval_s=0.6,
        scenarios=(cenario,),
    )
    app = create_app(settings=settings, testing=True)
    servidor = make_server("127.0.0.1", porta, app, threaded=True)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{porta}"

    try:
        for _ in range(30):
            try:
                _requisicao(base, "/api/estado")
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.1)
        else:
            raise AssertionError("O servidor de teste não iniciou.")

        status, _ = _requisicao(
            base,
            "/api/experimento/iniciar",
            {"cenario": "teste", "protecao": True},
        )
        assert status == 201
        estado = _aguardar_fim(base)
        assert estado["experimento"]["estado"] == "finalizado"
        com_protecao = estado["comparacao"]["com_protecao"]
        assert com_protecao is not None
        assert com_protecao["total"]["total"] > 0
        assert com_protecao["total"]["rejeitado"] > 0
        assert com_protecao["legitimo"]["total"] > 0
        assert com_protecao["cenario"]["chave"] == "teste"

        status, _ = _requisicao(
            base,
            "/api/experimento/iniciar",
            {"cenario": "teste", "protecao": False},
        )
        assert status == 201
        estado = _aguardar_fim(base)
        sem_protecao = estado["comparacao"]["sem_protecao"]
        assert sem_protecao is not None
        assert sem_protecao["total"]["total"] > 0
        assert sem_protecao["total"]["rejeitado"] == 0
        assert sem_protecao["legitimo"]["total"] > 0
        assert estado["comparacao"]["com_protecao"] is not None
        assert estado["experimento"]["estado"] == "finalizado"

        status, _ = _requisicao(base, "/api/laboratorio/reiniciar", {})
        assert status == 200
        _, estado = _requisicao(base, "/api/estado")
        assert estado["metricas"]["total"]["total"] == 0
        assert estado["comparacao"]["com_protecao"] is None
    finally:
        servidor.shutdown()
        servidor.server_close()
        thread.join(timeout=3)
