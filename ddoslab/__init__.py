"""Fábrica da aplicação Flask do DDoSLab."""

from __future__ import annotations

import logging

from flask import Flask, jsonify, render_template, request

from .capacity import ServiceCapacity
from .config import Settings
from .experiment import ExperimentManager
from .metrics import MetricsStore
from .rate_limit import RateLimiterRegistry
from .web import bp

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, testing: bool = False) -> Flask:
    """Cria a aplicação e suas dependências em memória."""
    settings = settings or Settings()
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=16 * 1024,
        TESTING=testing,
    )
    app.json.ensure_ascii = False

    metrics = MetricsStore()
    limiter = RateLimiterRegistry(
        rate_per_second=settings.rate_limit_per_second,
        burst=settings.rate_limit_burst,
    )
    capacity = ServiceCapacity(
        max_concurrent=settings.max_concurrent,
        processing_ms=settings.processing_ms,
    )
    experiment = ExperimentManager(settings, metrics, limiter, capacity)

    app.extensions["ddoslab"] = {
        "settings": settings,
        "metrics": metrics,
        "rate_limit": limiter,
        "capacity": capacity,
        "experiment": experiment,
    }

    app.register_blueprint(bp)

    @app.after_request
    def cabecalhos_de_seguranca(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
            "frame-ancestors 'none'",
        )
        return response

    @app.errorhandler(400)
    def requisicao_invalida(_error):
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Requisição inválida."}), 400
        return (
            render_template(
                "erro.html",
                titulo="Requisição inválida",
                mensagem="A requisição enviada não pôde ser interpretada.",
                codigo=400,
            ),
            400,
        )

    @app.errorhandler(404)
    def nao_encontrado(_error):
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Rota não encontrada."}), 404
        return (
            render_template(
                "erro.html",
                titulo="Página não encontrada",
                mensagem="O endereço informado não existe neste laboratório.",
                codigo=404,
            ),
            404,
        )

    @app.errorhandler(405)
    def metodo_nao_permitido(_error):
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Método HTTP não permitido."}), 405
        return (
            render_template(
                "erro.html",
                titulo="Método não permitido",
                mensagem="Esta ação não é permitida por este método HTTP.",
                codigo=405,
            ),
            405,
        )

    @app.errorhandler(413)
    def corpo_muito_grande(_error):
        return jsonify({"erro": "Corpo da requisição acima do limite."}), 413

    @app.errorhandler(500)
    def erro_interno(error):
        logger.exception("Erro interno no laboratório: %s", error)
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Erro interno ao processar a solicitação."}), 500
        return (
            render_template(
                "erro.html",
                titulo="Erro interno",
                mensagem="O laboratório encontrou um erro inesperado.",
                codigo=500,
            ),
            500,
        )

    return app
