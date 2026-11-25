"""Rotas HTTP e API do painel do DDoSLab."""

from __future__ import annotations

import re
import time
from typing import Any

from flask import Blueprint, current_app, jsonify, make_response, render_template, request

from .experiment import ExperimentError

bp = Blueprint("web", __name__)

CLIENT_HEADER = "X-DDoSLab-Client"
CLIENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _dependencies() -> dict[str, Any]:
    return current_app.extensions["ddoslab"]


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def _erro(mensagem: str, status: int):
    response = make_response(jsonify({"erro": mensagem}), status)
    return _no_store(response)


@bp.get("/")
def painel():
    deps = _dependencies()
    settings = deps["settings"]
    return render_template(
        "index.html",
        cenarios=[scenario.as_dict() for scenario in settings.scenarios],
        limites=settings.public_limits(),
        equipe=[
            "Ivaldo Pureza Freire Júnior",
            "Diogo Soares Alves Barreto de Carvalho",
        ],
    )


@bp.get("/api/estado")
def estado():
    deps = _dependencies()
    settings = deps["settings"]
    metrics = deps["metrics"]
    manager = deps["experiment"]
    capacity = deps["capacity"]
    payload = {
        "agora": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "servidor": {
            "endereco_local": f"{settings.host}:{settings.port}",
            "url_servico": settings.service_url,
            "processamento_simulado_ms": settings.processing_ms,
            "concorrencia_maxima": settings.max_concurrent,
            "capacidade_teorica_por_s": round(
                settings.theoretical_capacity_per_s, 2
            ),
            "capacidade": capacity.status(),
        },
        "limites": settings.public_limits(),
        "cenarios": [scenario.as_dict() for scenario in settings.scenarios],
        "experimento": manager.status(),
        "metricas": metrics.snapshot(),
        "comparacao": manager.comparison(),
    }
    return _no_store(make_response(jsonify(payload)))


@bp.post("/api/experimento/iniciar")
def iniciar_experimento():
    deps = _dependencies()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _erro("Envie um JSON válido para iniciar o experimento.", 400)
    campos_extra = set(data) - {"cenario", "protecao"}
    if campos_extra:
        return _erro(
            "O experimento aceita apenas 'cenario' e 'protecao'; "
            "não existe configuração de alvo externo.",
            400,
        )
    cenario = data.get("cenario")
    protecao = data.get("protecao", False)
    if not isinstance(cenario, str):
        return _erro("Selecione um cenário permitido.", 400)
    if not isinstance(protecao, bool):
        return _erro("O campo de proteção deve ser verdadeiro ou falso.", 400)
    try:
        status = deps["experiment"].start(cenario, protecao)
    except ExperimentError as exc:
        return _erro(str(exc), 409)
    return _no_store(
        make_response(
            jsonify(
                {
                    "mensagem": "Experimento iniciado.",
                    "experimento": status,
                }
            ),
            201,
        )
    )


@bp.post("/api/experimento/parar")
def parar_experimento():
    if not request.is_json:
        return _erro("Esta ação exige o cabeçalho Content-Type application/json.", 415)
    deps = _dependencies()
    status = deps["experiment"].stop()
    return _no_store(
        make_response(
            jsonify(
                {
                    "mensagem": "Experimento interrompido e resultados preservados.",
                    "experimento": status,
                }
            )
        )
    )


@bp.post("/api/laboratorio/reiniciar")
def reiniciar_laboratorio():
    if not request.is_json:
        return _erro("Esta ação exige o cabeçalho Content-Type application/json.", 415)
    deps = _dependencies()
    status = deps["experiment"].reset()
    return _no_store(
        make_response(
            jsonify(
                {
                    "mensagem": "Laboratório reiniciado e métricas descartadas.",
                    "experimento": status,
                }
            )
        )
    )


@bp.get("/api/servico")
def servico():
    """Serviço propositalmente limitado, usado por todos os clientes do laboratório."""
    deps = _dependencies()
    settings = deps["settings"]
    metrics = deps["metrics"]
    limiter = deps["rate_limit"]
    capacity = deps["capacity"]
    manager = deps["experiment"]

    started = time.perf_counter()
    client_id = _client_id()
    role = manager.role_for(client_id)
    allowed, _wait_s = limiter.allow(client_id)
    if not allowed:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        metrics.record_response(client_id, role, "rejeitado", elapsed_ms)
        response = make_response(
            jsonify(
                {
                    "mensagem": "Limite de requisições deste cliente excedido.",
                    "cliente": client_id,
                    "papel": role,
                    "protecao_ativa": True,
                }
            ),
            429,
        )
        response.headers["Retry-After"] = str(limiter.retry_after_seconds())
        return _service_headers(response, client_id, role, elapsed_ms)

    if not capacity.try_acquire():
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        metrics.record_response(
            client_id,
            role,
            "falha_capacidade",
            elapsed_ms,
        )
        response = make_response(
            jsonify(
                {
                    "mensagem": "Capacidade de atendimento esgotada.",
                    "cliente": client_id,
                    "papel": role,
                    "protecao_ativa": limiter.enabled,
                }
            ),
            503,
        )
        return _service_headers(response, client_id, role, elapsed_ms)

    try:
        capacity.process()
    finally:
        capacity.release()

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    metrics.record_response(client_id, role, "sucesso", elapsed_ms)
    response = make_response(
        jsonify(
            {
                "mensagem": "Requisição atendida.",
                "cliente": client_id,
                "papel": role,
                "protecao_ativa": limiter.enabled,
                "processamento_simulado_ms": settings.processing_ms,
                "duracao_servidor_ms": round(elapsed_ms, 1),
            }
        )
    )
    return _service_headers(response, client_id, role, elapsed_ms)


def _client_id() -> str:
    """Aceita a identidade de laboratório apenas de conexões locais."""
    raw = (request.headers.get(CLIENT_HEADER) or "").strip()
    remote = request.remote_addr or "desconhecido"
    if remote == "127.0.0.1" and raw and CLIENT_PATTERN.fullmatch(raw):
        return raw
    safe_remote = re.sub(r"[^A-Za-z0-9_.-]", "-", remote)[:30]
    return f"navegador-{safe_remote}"


def _service_headers(response, client_id: str, role: str, elapsed_ms: float):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-DDoSLab-Client"] = client_id
    response.headers["X-DDoSLab-Papel"] = role
    response.headers["X-DDoSLab-Duracao-Ms"] = f"{elapsed_ms:.2f}"
    return response
