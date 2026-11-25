"""Coleta e agregação das métricas medidas durante o laboratório."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

OUTCOMES = ("sucesso", "rejeitado", "falha_capacidade")
ROLES = ("legitimo", "virtual")
ROLE_LABELS = {"legitimo": "Legítimo", "virtual": "Virtual"}


@dataclass
class Aggregate:
    """Contadores e latências de um cliente, papel ou total geral."""

    total: int = 0
    sucesso: int = 0
    rejeitado: int = 0
    falha_capacidade: int = 0
    falha_transporte: int = 0
    latencias: list[float] = field(default_factory=list)

    def record(self, outcome: str, latency_ms: float | None = None) -> None:
        self.total += 1
        if outcome == "sucesso":
            self.sucesso += 1
            if latency_ms is not None and math.isfinite(latency_ms):
                self.latencias.append(max(0.0, latency_ms))
        elif outcome == "rejeitado":
            self.rejeitado += 1
        elif outcome == "falha_capacidade":
            self.falha_capacidade += 1
        elif outcome == "falha_transporte":
            self.falha_transporte += 1
        else:
            raise ValueError("Resultado de requisição desconhecido.")

    @property
    def falhas_disponibilidade(self) -> int:
        return self.falha_capacidade + self.falha_transporte

    def latency_stats(self) -> dict[str, float | None]:
        if not self.latencias:
            return {"media": None, "p50": None, "p95": None}
        ordered = sorted(self.latencias)
        count = len(ordered)
        p95_index = max(0, math.ceil(0.95 * count) - 1)
        return {
            "media": round(sum(ordered) / count, 1),
            "p50": round(ordered[max(0, math.ceil(0.50 * count) - 1)], 1),
            "p95": round(ordered[p95_index], 1),
        }

    def as_dict(self) -> dict[str, object]:
        total = self.total
        stats = self.latency_stats()
        return {
            "total": total,
            "sucesso": self.sucesso,
            "rejeitado": self.rejeitado,
            "falha_capacidade": self.falha_capacidade,
            "falha_transporte": self.falha_transporte,
            "falhas_disponibilidade": self.falhas_disponibilidade,
            "taxa_sucesso": _percent(self.sucesso, total),
            "taxa_rejeicao": _percent(self.rejeitado, total),
            "taxa_falha": _percent(self.falhas_disponibilidade, total),
            "latencia_media_ms": stats["media"],
            "latencia_p50_ms": stats["p50"],
            "latencia_p95_ms": stats["p95"],
        }


@dataclass
class ClientAggregate(Aggregate):
    client_id: str = ""
    role: str = "legitimo"

    def as_dict(self) -> dict[str, object]:
        data = super().as_dict()
        data.update(
            {
                "cliente": self.client_id,
                "papel": self.role,
                "papel_rotulo": ROLE_LABELS.get(self.role, self.role),
            }
        )
        return data


@dataclass
class Bucket:
    second: int
    sucesso: int = 0
    rejeitado: int = 0
    falha_capacidade: int = 0
    falha_transporte: int = 0
    latencias: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        total = (
            self.sucesso
            + self.rejeitado
            + self.falha_capacidade
            + self.falha_transporte
        )
        return {
            "segundo": self.second,
            "sucesso": self.sucesso,
            "rejeitado": self.rejeitado,
            "falhas": self.falha_capacidade + self.falha_transporte,
            "falha_capacidade": self.falha_capacidade,
            "falha_transporte": self.falha_transporte,
            "total": total,
            "latencia_media_ms": (
                round(sum(self.latencias) / len(self.latencias), 1)
                if self.latencias
                else None
            ),
            "latencia_p95_ms": _p95(self.latencias),
        }


class MetricsStore:
    """Armazena métricas reais em memória, com acesso concorrente seguro."""

    def __init__(self, timeline_seconds: int = 60) -> None:
        self.timeline_seconds = timeline_seconds
        self._lock = threading.RLock()
        self._bucket_limit = max(120, timeline_seconds * 2)
        self._buckets: deque[Bucket] = deque()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._total = Aggregate()
            self._by_role = {role: Aggregate() for role in ROLES}
            self._by_client: dict[str, ClientAggregate] = {}
            self._buckets.clear()
            self._started_at = _now_iso()
            self._last_event_at: str | None = None

    def _client(self, client_id: str, role: str) -> ClientAggregate:
        client = self._by_client.get(client_id)
        if client is None:
            client = ClientAggregate(client_id=client_id, role=role)
            self._by_client[client_id] = client
        return client

    def _bucket_for(self, second: int) -> Bucket:
        if self._buckets and self._buckets[-1].second == second:
            return self._buckets[-1]
        bucket = Bucket(second=second)
        self._buckets.append(bucket)
        cutoff = second - self._bucket_limit
        while self._buckets and self._buckets[0].second < cutoff:
            self._buckets.popleft()
        return bucket

    def record_response(
        self,
        client_id: str,
        role: str,
        outcome: str,
        latency_ms: float,
    ) -> None:
        """Registra uma resposta HTTP efetivamente medida pelo servidor."""
        if outcome not in OUTCOMES:
            raise ValueError("Resultado de resposta inválido.")
        with self._lock:
            self._total.record(outcome, latency_ms)
            self._by_role.setdefault(role, Aggregate()).record(outcome, latency_ms)
            self._client(client_id, role).record(outcome, latency_ms)
            bucket = self._bucket_for(int(time.time()))
            setattr(bucket, outcome, getattr(bucket, outcome) + 1)
            if outcome == "sucesso" and math.isfinite(latency_ms):
                bucket.latencias.append(max(0.0, latency_ms))
            self._last_event_at = _now_iso()

    def record_transport_failure(
        self,
        client_id: str,
        role: str,
        latency_ms: float | None = None,
    ) -> None:
        """Registra falha em que não houve resposta HTTP observada pelo cliente."""
        with self._lock:
            self._total.record("falha_transporte", None)
            self._by_role.setdefault(role, Aggregate()).record(
                "falha_transporte", None
            )
            self._client(client_id, role).record("falha_transporte", None)
            bucket = self._bucket_for(int(time.time()))
            bucket.falha_transporte += 1
            self._last_event_at = _now_iso()

    def client_snapshot(self, client_id: str) -> dict[str, object] | None:
        with self._lock:
            client = self._by_client.get(client_id)
            return None if client is None else client.as_dict()

    def snapshot(self) -> dict[str, object]:
        """Monta uma fotografia consistente para o painel em tempo real."""
        with self._lock:
            now_second = int(time.time())
            bucket_map = {bucket.second: bucket for bucket in self._buckets}
            # Depois que o experimento termina, congela a janela na última
            # amostra para que os gráficos continuem legíveis na apresentação.
            end_second = now_second
            if self._buckets:
                ultima = self._buckets[-1].second
                if now_second - ultima >= self.timeline_seconds:
                    end_second = ultima
            first_second = end_second - self.timeline_seconds + 1
            series = []
            for second in range(first_second, end_second + 1):
                bucket = bucket_map.get(second)
                if bucket is None:
                    series.append(
                        {
                            "segundo": second,
                            "sucesso": 0,
                            "rejeitado": 0,
                            "falhas": 0,
                            "falha_capacidade": 0,
                            "falha_transporte": 0,
                            "total": 0,
                            "latencia_media_ms": None,
                            "latencia_p95_ms": None,
                        }
                    )
                else:
                    series.append(bucket.as_dict())

            clients = sorted(
                (client.as_dict() for client in self._by_client.values()),
                key=lambda item: (-int(item["total"]), str(item["cliente"])),
            )
            return {
                "total": self._total.as_dict(),
                "por_papel": {
                    role: self._by_role.get(role, Aggregate()).as_dict()
                    for role in ROLES
                },
                "por_cliente": clients,
                "serie_temporal": series,
                "janela_fim_segundo": end_second,
                "janela_ao_vivo": end_second == now_second,
                "iniciado_em": self._started_at,
                "ultimo_evento_em": self._last_event_at,
            }


def _percent(part: int, total: int) -> float:
    return round((part / total) * 100.0, 1) if total else 0.0


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return round(ordered[index], 1)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
