"""Testes das rotas HTTP, validação e respostas do serviço limitado."""

from __future__ import annotations

from ddoslab.config import Settings


def test_painel_e_renderizado_em_portugues(client):
    resposta = client.get("/")
    html = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'lang="pt-BR"' in html
    assert "DDoSLab" in html
    assert "Distribuição simulada" in html
    assert "Acessar o serviço agora" in html
    assert "Ivaldo Pureza Freire Júnior" in html
    assert "Diogo Soares Alves Barreto de Carvalho" in html


def test_estado_expoe_metricas_limites_e_seguranca(client):
    resposta = client.get("/api/estado")
    dados = resposta.get_json()

    assert resposta.status_code == 200
    assert resposta.headers["Cache-Control"] == "no-store"
    assert resposta.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in resposta.headers["Content-Security-Policy"]
    assert dados["servidor"]["endereco_local"] == "127.0.0.1:5000"
    assert dados["experimento"]["estado"] == "ocioso"
    assert dados["metricas"]["total"]["total"] == 0
    assert len(dados["metricas"]["serie_temporal"]) == 60
    assert len(dados["cenarios"]) == 3


def test_servico_bem_sucedido_registra_metrica(client):
    resposta = client.get(
        "/api/servico",
        headers={"X-DDoSLab-Client": "cliente-teste"},
    )
    dados = resposta.get_json()

    assert resposta.status_code == 200
    assert dados["mensagem"] == "Requisição atendida."
    assert dados["cliente"] == "cliente-teste"
    assert resposta.headers["X-DDoSLab-Client"] == "cliente-teste"
    assert resposta.headers["X-DDoSLab-Papel"] == "legitimo"

    estado = client.get("/api/estado").get_json()
    assert estado["metricas"]["total"]["sucesso"] == 1
    assert estado["metricas"]["por_cliente"][0]["cliente"] == "cliente-teste"


def test_limitador_por_cliente_e_real(app, client):
    app.extensions["ddoslab"]["rate_limit"].configure(True)
    cabecalhos = {"X-DDoSLab-Client": "cliente-limitado"}

    assert client.get("/api/servico", headers=cabecalhos).status_code == 200
    segunda = client.get("/api/servico", headers=cabecalhos)

    assert segunda.status_code == 429
    assert segunda.headers["Retry-After"] == "1"
    assert segunda.get_json()["protecao_ativa"] is True

    estado = client.get("/api/estado").get_json()
    assert estado["metricas"]["por_papel"]["legitimo"]["rejeitado"] == 1


def test_capacidade_esgotada_responde_503(app, client):
    capacidade = app.extensions["ddoslab"]["capacity"]
    vagas_ocupadas = 0
    while capacidade.try_acquire():
        vagas_ocupadas += 1
    assert vagas_ocupadas == capacidade.max_concurrent
    try:
        resposta = client.get("/api/servico")
    finally:
        for _ in range(vagas_ocupadas):
            capacidade.release()

    assert resposta.status_code == 503
    assert resposta.get_json()["mensagem"] == "Capacidade de atendimento esgotada."

    estado = client.get("/api/estado").get_json()
    assert estado["metricas"]["total"]["falha_capacidade"] == 1


def test_iniciar_com_cenario_invalido_falha_em_portugues(client):
    resposta = client.post(
        "/api/experimento/iniciar",
        json={"cenario": "externo", "protecao": False},
    )

    assert resposta.status_code == 409
    assert "Cenário inválido" in resposta.get_json()["erro"]


def test_iniciar_sem_json_valido_falha(client):
    resposta = client.post(
        "/api/experimento/iniciar",
        data="não é json",
        content_type="text/plain",
    )

    assert resposta.status_code == 400
    assert "JSON válido" in resposta.get_json()["erro"]


def test_iniciar_recusa_configuracao_de_alvo_externo(client):
    resposta = client.post(
        "/api/experimento/iniciar",
        json={
            "cenario": "moderado",
            "protecao": False,
            "alvo": "http://exemplo.invalido",
        },
    )

    assert resposta.status_code == 400
    assert "alvo externo" in resposta.get_json()["erro"]


def test_protecao_precisa_ser_booleana(client):
    resposta = client.post(
        "/api/experimento/iniciar",
        json={"cenario": "moderado", "protecao": "sim"},
    )

    assert resposta.status_code == 400
    assert "verdadeiro ou falso" in resposta.get_json()["erro"]


def test_reiniciar_sem_execucao_limpa_o_estado(client):
    client.get("/api/servico")
    resposta = client.post("/api/laboratorio/reiniciar", json={})

    assert resposta.status_code == 200
    estado = client.get("/api/estado").get_json()
    assert estado["experimento"]["estado"] == "ocioso"
    assert estado["metricas"]["total"]["total"] == 0
    assert estado["comparacao"] == {"com_protecao": None, "sem_protecao": None}


def test_acao_de_estado_sem_json_e_recusada(client):
    resposta = client.post(
        "/api/laboratorio/reiniciar",
        data="reiniciar=sim",
        content_type="application/x-www-form-urlencoded",
    )

    assert resposta.status_code == 415
    assert "application/json" in resposta.get_json()["erro"]


def test_api_desconhecida_responde_em_portugues(client):
    resposta = client.get("/api/nao-existe")

    assert resposta.status_code == 404
    assert resposta.get_json()["erro"] == "Rota não encontrada."


def test_limites_sao_fixos_e_somente_locais():
    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.service_url.startswith("http://127.0.0.1:5000/")
    assert settings.max_clients == 8
    assert settings.max_planned_requests == 1600
    assert all(
        cenario.planned_requests <= settings.max_planned_requests
        for cenario in settings.scenarios
    )
