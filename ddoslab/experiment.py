"""Orquestração do experimento local e geração de carga controlada."""

from __future__ import annotations

import http.client
import logging
import threading
import time
import uuid
from datetime import datetime

from .capacity import ServiceCapacity
from .config import Scenario, Settings
from .metrics import MetricsStore
from .rate_limit import RateLimiterRegistry

logger = logging.getLogger(__name__)

PROBE_CLIENT_ID = "sonda-legitima"


class ExperimentError(Exception):
    """Erro de validação ou de estado do experimento."""


class LocalHttpClient:
    """Cliente HTTP restrito ao serviço local do próprio laboratório."""

    def __init__(
        self,
        settings: Settings,
        metrics: MetricsStore,
        client_id: str,
        role: str,
    ) -> None:
        self.settings = settings
        self.metrics = metrics
        self.client_id = client_id
        self.role = role
        self._connection: http.client.HTTPConnection | None = None

    def _connect(self) -> http.client.HTTPConnection:
        if self._connection is None:
            self._connection = http.client.HTTPConnection(
                self.settings.host,
                self.settings.port,
                timeout=self.settings.client_timeout_s,
            )
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    def call(self) -> int | None:
        """Executa uma requisição e mede a falha de transporte quando existir."""
        started = time.perf_counter()
        try:
            connection = self._connect()
            connection.request(
                "GET",
                self.settings.service_path,
                headers={
                    "Accept": "application/json",
                    "X-DDoSLab-Client": self.client_id,
                },
            )
            response = connection.getresponse()
            response.read()
            if response.will_close:
                self.close()
            return int(response.status)
        except (OSError, http.client.HTTPException):
            self.close()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.metrics.record_transport_failure(
                self.client_id,
                self.role,
                elapsed_ms,
            )
            return None


class VirtualClient(threading.Thread):
    """Uma thread que envia requisições reais, com taxa e volume limitados."""

    def __init__(
        self,
        *,
        index: int,
        settings: Settings,
        metrics: MetricsStore,
        scenario: Scenario,
        stop_event: threading.Event,
        start_delay_s: float,
    ) -> None:
        super().__init__(name=f"cliente-virtual-{index:02d}", daemon=True)
        self.client_id = f"virtual-{index:02d}"
        self.settings = settings
        self.scenario = scenario
        self.stop_event = stop_event
        self.start_delay_s = start_delay_s
        self.http = LocalHttpClient(settings, metrics, self.client_id, "virtual")

    def run(self) -> None:
        interval = 1.0 / self.scenario.rate_per_client
        max_requests = self.scenario.rate_per_client * self.scenario.duration_s
        sent = 0
        next_at = time.monotonic() + self.start_delay_s
        try:
            while sent < max_requests and not self.stop_event.is_set():
                wait_s = next_at - time.monotonic()
                if wait_s > 0 and self.stop_event.wait(wait_s):
                    break
                if self.stop_event.is_set():
                    break
                self.http.call()
                sent += 1
                # Não tenta compensar atrasos com rajadas: o gerador é limitado.
                next_at = max(next_at + interval, time.monotonic())
        finally:
            self.http.close()


class LegitProbe(threading.Thread):
    """Sonda automática que representa o usuário legítimo durante o cenário."""

    def __init__(
        self,
        settings: Settings,
        metrics: MetricsStore,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="sonda-legitima", daemon=True)
        self.settings = settings
        self.stop_event = stop_event
        self.http = LocalHttpClient(settings, metrics, PROBE_CLIENT_ID, "legitimo")

    def run(self) -> None:
        next_at = time.monotonic()
        try:
            while not self.stop_event.is_set():
                wait_s = next_at - time.monotonic()
                if wait_s > 0 and self.stop_event.wait(wait_s):
                    break
                if self.stop_event.is_set():
                    break
                self.http.call()
                next_at = max(
                    next_at + self.settings.legit_probe_interval_s,
                    time.monotonic(),
                )
        finally:
            self.http.close()


class ExperimentManager:
    """Controla início, parada, reinício e o resumo comparável das execuções."""

    def __init__(
        self,
        settings: Settings,
        metrics: MetricsStore,
        limiter: RateLimiterRegistry,
        capacity: ServiceCapacity,
    ) -> None:
        self.settings = settings
        self.metrics = metrics
        self.limiter = limiter
        self.capacity = capacity
        self._lock = threading.RLock()
        self._finish_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._state = "ocioso"
        self._scenario: Scenario | None = None
        self._protection = False
        self._roles: dict[str, str] = {}
        self._threads: list[threading.Thread] = []
        self._monitor: threading.Thread | None = None
        self._run_id: str | None = None
        self._started_at: str | None = None
        self._ended_at: str | None = None
        self._started_monotonic: float | None = None
        self._duration_measured_s: float | None = None
        self._finish_reason: str | None = None
        self._finalized = True
        self._comparison: dict[bool, dict[str, object]] = {}
        self._last_summary: dict[str, object] | None = None

    def role_for(self, client_id: str) -> str:
        """Resolve o papel pelo cadastro do experimento, não por dado do painel."""
        with self._lock:
            return self._roles.get(client_id, "legitimo")

    def start(self, scenario_key: str, protection_enabled: bool) -> dict[str, object]:
        scenario = self.settings.scenario(scenario_key)
        if scenario is None:
            raise ExperimentError("Cenário inválido. Selecione uma opção permitida.")
        if not isinstance(protection_enabled, bool):
            raise ExperimentError("O estado da proteção deve ser verdadeiro ou falso.")

        with self._lock:
            if self._state == "executando":
                raise ExperimentError("Já existe um experimento em execução.")
            self.metrics.reset()
            self.limiter.configure(protection_enabled)
            self._state = "executando"
            self._scenario = scenario
            self._protection = protection_enabled
            self._run_id = uuid.uuid4().hex[:8]
            self._started_at = _now_iso()
            self._ended_at = None
            self._started_monotonic = time.monotonic()
            self._duration_measured_s = None
            self._finish_reason = None
            self._finalized = False
            self._last_summary = None
            self._stop_event = threading.Event()
            self._roles = {
                f"virtual-{index:02d}": "virtual"
                for index in range(1, scenario.clients + 1)
            }
            self._roles[PROBE_CLIENT_ID] = "legitimo"

            self._threads = []
            # Espalha os clientes dentro de um ciclo do limitador para evitar
            # rajadas sincronizadas que distorceriam a comparação.
            espacamento = (
                1.0 / self.settings.rate_limit_per_second / scenario.clients
            )
            for index in range(1, scenario.clients + 1):
                worker = VirtualClient(
                    index=index,
                    settings=self.settings,
                    metrics=self.metrics,
                    scenario=scenario,
                    stop_event=self._stop_event,
                    start_delay_s=(index - 1) * espacamento,
                )
                self._threads.append(worker)
            probe = LegitProbe(self.settings, self.metrics, self._stop_event)
            self._threads.append(probe)

            self._monitor = threading.Thread(
                target=self._watch_duration,
                name="monitor-do-experimento",
                daemon=True,
            )
            for thread in self._threads:
                thread.start()
            self._monitor.start()
            logger.info(
                "Experimento %s iniciado: cenário=%s, proteção=%s",
                self._run_id,
                scenario.key,
                protection_enabled,
            )
        return self.status()

    def _watch_duration(self) -> None:
        with self._lock:
            scenario = self._scenario
            stop_event = self._stop_event
        if scenario is None:
            return
        if stop_event.wait(float(scenario.duration_s)):
            return
        self._finish("duracao")

    def stop(self) -> dict[str, object]:
        with self._lock:
            if self._state != "executando":
                return self.status()
            event = self._stop_event
        event.set()
        self._finish("manual")
        return self.status()

    def _finish(self, reason: str) -> None:
        with self._finish_lock:
            with self._lock:
                if self._state != "executando" or self._finalized:
                    return
                self._finalized = True
                self._finish_reason = reason
                event = self._stop_event
                threads = list(self._threads)
                ended_monotonic = time.monotonic()
                started_monotonic = self._started_monotonic
            event.set()
            deadline = time.monotonic() + max(
                2.0,
                self.settings.client_timeout_s + 1.0,
            )
            for thread in threads:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                thread.join(timeout=remaining)

            measured = (
                max(0.0, ended_monotonic - started_monotonic)
                if started_monotonic is not None
                else 0.0
            )
            summary = self._build_summary(measured, reason)
            with self._lock:
                self._duration_measured_s = round(measured, 1)
                self._ended_at = _now_iso()
                self._state = "finalizado"
                self._last_summary = summary
                self._comparison[self._protection] = summary
                run_id = self._run_id
            logger.info(
                "Experimento %s finalizado: motivo=%s, sucesso=%s, rejeitado=%s",
                run_id,
                reason,
                summary["total"]["sucesso"],
                summary["total"]["rejeitado"],
            )

    def _build_summary(self, duration_s: float, reason: str) -> dict[str, object]:
        snapshot = self.metrics.snapshot()
        overall = snapshot["total"]
        probe = self.metrics.client_snapshot(PROBE_CLIENT_ID)
        legit = probe or _empty_client_summary(PROBE_CLIENT_ID, "legitimo")
        virtual = snapshot["por_papel"]["virtual"]
        return {
            "id_execucao": self._run_id,
            "cenario": self._scenario.as_dict() if self._scenario else None,
            "protecao_ativa": self._protection,
            "motivo_encerramento": reason,
            "iniciado_em": self._started_at,
            "finalizado_em": _now_iso(),
            "duracao_medida_s": round(duration_s, 1),
            "total": overall,
            "legitimo": legit,
            "virtual": virtual,
            "clientes": snapshot["por_cliente"],
        }

    def reset(self) -> dict[str, object]:
        with self._lock:
            running = self._state == "executando"
        if running:
            self.stop()
        with self._lock:
            self._state = "ocioso"
            self._scenario = None
            self._protection = False
            self._roles = {}
            self._threads = []
            self._monitor = None
            self._run_id = None
            self._started_at = None
            self._ended_at = None
            self._started_monotonic = None
            self._duration_measured_s = None
            self._finish_reason = None
            self._comparison = {}
            self._last_summary = None
            self._stop_event = threading.Event()
            self._finalized = True
        self.metrics.reset()
        self.limiter.reset(enabled=False)
        logger.info("Laboratório reiniciado e métricas descartadas.")
        return self.status()

    def comparison(self) -> dict[str, object]:
        with self._lock:
            return {
                "com_protecao": self._comparison.get(True),
                "sem_protecao": self._comparison.get(False),
            }

    def status(self) -> dict[str, object]:
        with self._lock:
            now_monotonic = time.monotonic()
            elapsed = 0.0
            remaining = 0.0
            if self._state == "executando" and self._started_monotonic is not None:
                elapsed = max(0.0, now_monotonic - self._started_monotonic)
                if self._scenario is not None:
                    remaining = max(0.0, self._scenario.duration_s - elapsed)
            return {
                "estado": self._state,
                "id_execucao": self._run_id,
                "cenario": self._scenario.as_dict() if self._scenario else None,
                "protecao_ativa": self._protection,
                "iniciado_em": self._started_at,
                "finalizado_em": self._ended_at,
                "decorrido_s": round(elapsed, 1),
                "restante_s": round(remaining, 1),
                "duracao_medida_s": self._duration_measured_s,
                "motivo_encerramento": self._finish_reason,
                "protecao_configurada": {
                    "requisicoes_por_segundo": self.limiter.rate_per_second,
                    "rajada": self.limiter.burst,
                },
                "ultimo_resumo": self._last_summary,
            }


def _empty_client_summary(client_id: str, role: str) -> dict[str, object]:
    return {
        "cliente": client_id,
        "papel": role,
        "papel_rotulo": "Legítimo",
        "total": 0,
        "sucesso": 0,
        "rejeitado": 0,
        "falha_capacidade": 0,
        "falha_transporte": 0,
        "falhas_disponibilidade": 0,
        "taxa_sucesso": 0.0,
        "taxa_rejeicao": 0.0,
        "taxa_falha": 0.0,
        "latencia_media_ms": None,
        "latencia_p50_ms": None,
        "latencia_p95_ms": None,
    }


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
