"""Fixtures compartilhadas pelos testes do DDoSLab."""

from __future__ import annotations

import dataclasses

import pytest

from ddoslab import create_app
from ddoslab.config import Settings


@pytest.fixture
def configuracoes_rapidas() -> Settings:
    return dataclasses.replace(
        Settings(),
        processing_ms=25,
        client_timeout_s=2.0,
        legit_probe_interval_s=0.2,
    )


@pytest.fixture
def app(configuracoes_rapidas):
    return create_app(settings=configuracoes_rapidas, testing=True)


@pytest.fixture
def client(app):
    return app.test_client()
