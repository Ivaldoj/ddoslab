"""Configuração fixa e limites de segurança do DDoSLab."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    """Descreve um cenário de carga controlado e imutável."""

    key: str
    label: str
    description: str
    clients: int
    rate_per_client: int
    duration_s: int

    @property
    def planned_requests(self) -> int:
        """Volume máximo planejado para o gerador de carga."""
        return self.clients * self.rate_per_client * self.duration_s

    def as_dict(self) -> dict[str, object]:
        return {
            "chave": self.key,
            "rotulo": self.label,
            "descricao": self.description,
            "clientes_virtuais": self.clients,
            "taxa_por_cliente": self.rate_per_client,
            "duracao_s": self.duration_s,
            "total_planejado": self.planned_requests,
        }


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="moderado",
        label="Carga moderada",
        description="Poucos clientes virtuais para observar o comportamento inicial.",
        clients=4,
        rate_per_client=4,
        duration_s=10,
    ),
    Scenario(
        key="elevado",
        label="Carga elevada",
        description="Cenário recomendado para comparar com e sem proteção.",
        clients=6,
        rate_per_client=8,
        duration_s=15,
    ),
    Scenario(
        key="pico",
        label="Pico controlado",
        description="Maior volume permitido pelo laboratório, ainda com limites rígidos.",
        clients=8,
        rate_per_client=10,
        duration_s=20,
    ),
)


@dataclass(frozen=True)
class Settings:
    """Parâmetros fixos do laboratório.

    Não existe campo de alvo externo: o gerador sempre usa o próprio servidor
    Flask em 127.0.0.1. Os valores abaixo também funcionam como travas de
    segurança para qualquer chamada da interface.
    """

    host: str = "127.0.0.1"
    port: int = 5000
    service_path: str = "/api/servico"
    max_concurrent: int = 4
    processing_ms: int = 180
    rate_limit_per_second: float = 2.0
    rate_limit_burst: int = 1
    legit_probe_interval_s: float = 1.0
    client_timeout_s: float = 3.0
    max_clients: int = 8
    max_rate_per_client: int = 10
    max_duration_s: int = 20
    max_planned_requests: int = 1600
    scenarios: tuple[Scenario, ...] = SCENARIOS

    def __post_init__(self) -> None:
        if self.host != "127.0.0.1":
            raise ValueError("O laboratório só pode escutar em 127.0.0.1.")
        if self.max_concurrent < 1:
            raise ValueError("O limite de concorrência deve ser positivo.")
        if self.processing_ms < 1:
            raise ValueError("O processamento simulado deve ser positivo.")
        if not self.scenarios:
            raise ValueError("É necessário definir ao menos um cenário.")
        for scenario in self.scenarios:
            if scenario.clients < 1 or scenario.clients > self.max_clients:
                raise ValueError("Cenário com quantidade de clientes fora do limite.")
            if (
                scenario.rate_per_client < 1
                or scenario.rate_per_client > self.max_rate_per_client
            ):
                raise ValueError("Cenário com taxa por cliente fora do limite.")
            if scenario.duration_s < 1 or scenario.duration_s > self.max_duration_s:
                raise ValueError("Cenário com duração fora do limite.")
            if scenario.planned_requests > self.max_planned_requests:
                raise ValueError("Cenário com volume planejado acima do limite.")

    @property
    def service_url(self) -> str:
        """URL local usada exclusivamente pelo gerador de carga."""
        return f"http://{self.host}:{self.port}{self.service_path}"

    @property
    def theoretical_capacity_per_s(self) -> float:
        """Capacidade máxima derivada da configuração, não medida em execução."""
        return self.max_concurrent / (self.processing_ms / 1000.0)

    def scenario(self, key: str) -> Scenario | None:
        for scenario in self.scenarios:
            if scenario.key == key:
                return scenario
        return None

    def public_limits(self) -> dict[str, object]:
        """Limites que podem ser exibidos sem revelar estado interno mutável."""
        return {
            "endereco_local": f"{self.host}:{self.port}",
            "concorrencia_maxima": self.max_concurrent,
            "processamento_simulado_ms": self.processing_ms,
            "limite_por_cliente_s": self.rate_limit_per_second,
            "rajada_por_cliente": self.rate_limit_burst,
            "max_clientes_virtuais": self.max_clients,
            "max_taxa_por_cliente": self.max_rate_per_client,
            "duracao_maxima_s": self.max_duration_s,
            "volume_maximo_planejado": self.max_planned_requests,
            "capacidade_teorica_por_s": round(self.theoretical_capacity_per_s, 2),
        }
