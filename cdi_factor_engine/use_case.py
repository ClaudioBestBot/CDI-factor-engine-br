"""Caso de uso: calcular o FatorJ contratado a partir de uma série de taxas.

Este é o ponto de entrada público do motor. Independente de interface,
banco de dados e Finance Genie: recebe a série de taxas já carregada pelo
chamador (sem nenhuma coleta automática) e devolve o resultado mínimo
especificado, com trilha de auditoria opcional.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Sequence

from .audit import AuditRecord, build_audit_record
from .domain.types import FactorJRequest, FactorJResult, RateObservation
from .factor_j import calculate
from .methodology import METHODOLOGY_VERSION


def calculate_factor_j(
    rate_series: Sequence[RateObservation],
    requested_start_date: date,
    requested_end_date: date,
    percentual: Decimal,
    methodology_version: str = METHODOLOGY_VERSION,
    data_version: str = "unspecified",
) -> FactorJResult:
    """Calcula o FatorJ contratado para o intervalo e percentual informados.

    ``rate_series`` deve conter as taxas anuais (base 252, forma decimal)
    publicadas nas datas relevantes, incluindo, quando disponível, a data
    inicial solicitada. A série não precisa estar ordenada previamente.
    """

    request = FactorJRequest(
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        percentual=percentual,
        rate_series=tuple(rate_series),
        methodology_version=methodology_version,
        data_version=data_version,
    )
    return calculate(request)


def calculate_factor_j_with_audit(
    rate_series: Sequence[RateObservation],
    requested_start_date: date,
    requested_end_date: date,
    percentual: Decimal,
    methodology_version: str = METHODOLOGY_VERSION,
    data_version: str = "unspecified",
) -> AuditRecord:
    """Como :func:`calculate_factor_j`, mas devolve também a trilha de auditoria."""

    result = calculate_factor_j(
        rate_series=rate_series,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        percentual=percentual,
        methodology_version=methodology_version,
        data_version=data_version,
    )
    return build_audit_record(result, rate_series, percentual)
