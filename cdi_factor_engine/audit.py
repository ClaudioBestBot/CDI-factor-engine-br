"""Metadados e trilha de auditoria do cálculo.

Fornece um resumo determinístico (hash das entradas) que permite
verificar, a posteriori, que um resultado foi produzido a partir de uma
série de taxas e parâmetros específicos, sem depender de nenhuma fonte
externa nesta etapa.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence

from .domain.types import FactorJResult, RateObservation


@dataclass(frozen=True)
class AuditRecord:
    generated_at: str
    methodology_version: str
    data_version: str
    input_observation_count: int
    input_fingerprint: str
    result: FactorJResult

    def to_json_dict(self) -> dict:
        payload = self.result.to_json_dict()
        payload.update(
            {
                "generated_at": self.generated_at,
                "input_observation_count": self.input_observation_count,
                "input_fingerprint": self.input_fingerprint,
            }
        )
        return payload


def fingerprint_series(
    rate_series: Sequence[RateObservation],
    requested_start_date: date,
    requested_end_date: date,
    percentual: Decimal,
) -> str:
    """SHA-256 determinístico das entradas do cálculo, para auditoria."""

    hasher = hashlib.sha256()
    hasher.update(requested_start_date.isoformat().encode("utf-8"))
    hasher.update(requested_end_date.isoformat().encode("utf-8"))
    hasher.update(str(percentual).encode("utf-8"))
    for observation in sorted(rate_series, key=lambda obs: obs.reference_date):
        hasher.update(observation.reference_date.isoformat().encode("utf-8"))
        hasher.update(str(observation.annual_rate).encode("utf-8"))
    return hasher.hexdigest()


def build_audit_record(
    result: FactorJResult,
    rate_series: Sequence[RateObservation],
    percentual: Decimal,
) -> AuditRecord:
    fingerprint = fingerprint_series(
        rate_series,
        result.requested_start_date,
        result.requested_end_date,
        percentual,
    )
    return AuditRecord(
        generated_at=datetime.now(timezone.utc).isoformat(),
        methodology_version=result.methodology_version,
        data_version=result.data_version,
        input_observation_count=len(rate_series),
        input_fingerprint=fingerprint,
        result=result,
    )
