"""Tipos de domínio: observações de taxa, requisição e resultado do cálculo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class RateObservation:
    """Uma taxa anual (CDI/DI, base 252) publicada em uma data de referência.

    ``annual_rate`` é a taxa anual em forma decimal (por exemplo,
    ``Decimal("0.064")`` para 6,4% a.a.), nunca em percentual (``6.4``) nem
    ``float``.
    """

    reference_date: date
    annual_rate: Decimal


@dataclass(frozen=True)
class FactorJRequest:
    """Requisição de cálculo do FatorJ para um contrato."""

    requested_start_date: date
    requested_end_date: date
    percentual: Decimal
    rate_series: tuple[RateObservation, ...]
    methodology_version: str
    data_version: str


@dataclass(frozen=True)
class FactorJResult:
    """Resultado mínimo do cálculo, conforme especificado na issue."""

    requested_start_date: date
    requested_end_date: date
    effective_end_date: date
    observations: int
    raw_factor: Decimal
    operational_factor_trunc6: Decimal
    cutoff_reason: str
    precision_mode: str
    methodology_version: str
    data_version: str

    def to_json_dict(self) -> dict:
        """Serializa o resultado para um dicionário apto a virar JSON.

        Todos os valores decimais são serializados como texto, nunca como
        número de ponto flutuante.
        """

        return {
            "requested_start_date": self.requested_start_date.isoformat(),
            "requested_end_date": self.requested_end_date.isoformat(),
            "effective_end_date": self.effective_end_date.isoformat(),
            "observations": self.observations,
            "raw_factor": str(self.raw_factor),
            "operational_factor_trunc6": str(self.operational_factor_trunc6),
            "cutoff_reason": self.cutoff_reason,
            "precision_mode": self.precision_mode,
            "methodology_version": self.methodology_version,
            "data_version": self.data_version,
        }
