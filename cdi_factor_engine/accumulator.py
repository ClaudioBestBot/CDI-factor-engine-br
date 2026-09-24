"""Acumulação da série de fatores diários no intervalo do contrato.

Aplica a convenção temporal: acumula observações em
``(requested_start_date, effective_end_date]``, calcula a
``effective_end_date`` (data solicitada, se publicada e validada, ou a
última data publicada anterior) e nunca preenche lacunas silenciosamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from typing import Sequence

from .calendar import is_business_day
from .daily_factor import compute_contract_factor, compute_daily_di_factor
from .decimal_policy import INTERNAL_PRECISION
from .domain.types import RateObservation
from .validation import validate_series

CUTOFF_REQUESTED_END_DATE_PUBLISHED = "requested_end_date_published"
CUTOFF_FALLBACK_TO_LAST_PUBLISHED_RATE = "fallback_to_last_published_rate_before_requested_end_date"
CUTOFF_START_EQUALS_END = "start_equals_end"


class NoRateDataError(ValueError):
    """Não há nenhuma taxa publicada em ou antes da data final solicitada."""


class InvalidDateRangeError(ValueError):
    """A data inicial solicitada é posterior à data final solicitada."""


@dataclass(frozen=True)
class AccumulationResult:
    effective_end_date: date
    observations: int
    raw_factor: Decimal
    cutoff_reason: str


def accumulate(
    rate_series: Sequence[RateObservation],
    requested_start_date: date,
    requested_end_date: date,
    percentual: Decimal,
) -> AccumulationResult:
    if requested_start_date > requested_end_date:
        raise InvalidDateRangeError(
            "requested_start_date não pode ser posterior a requested_end_date"
        )

    # Valida a série na ordem exatamente informada: uma série desordenada
    # deve falhar, não ser silenciosamente reordenada.
    validate_series(rate_series)
    sorted_series = sorted(rate_series, key=lambda obs: obs.reference_date)

    if requested_start_date == requested_end_date:
        return AccumulationResult(
            effective_end_date=requested_end_date,
            observations=0,
            raw_factor=Decimal(1),
            cutoff_reason=CUTOFF_START_EQUALS_END,
        )

    published_up_to_requested_end = [
        obs for obs in sorted_series if obs.reference_date <= requested_end_date
    ]
    if not published_up_to_requested_end:
        raise NoRateDataError(
            "Nenhuma taxa publicada em ou antes de "
            f"{requested_end_date.isoformat()}"
        )

    last_published = published_up_to_requested_end[-1]
    if last_published.reference_date == requested_end_date:
        effective_end_date = requested_end_date
        cutoff_reason = CUTOFF_REQUESTED_END_DATE_PUBLISHED
    else:
        effective_end_date = last_published.reference_date
        cutoff_reason = CUTOFF_FALLBACK_TO_LAST_PUBLISHED_RATE

    raw_factor = Decimal(1)
    observations = 0
    # A acumulação (multiplicação de até centenas de fatores diários) roda
    # em um contexto decimal de alta precisão local, para que nenhum
    # arredondamento intermediário implícito do contexto padrão (28 dígitos)
    # seja aplicado antes da truncagem operacional final.
    with localcontext() as ctx:
        ctx.prec = INTERNAL_PRECISION
        for obs in sorted_series:
            if obs.reference_date <= requested_start_date:
                continue
            if obs.reference_date > effective_end_date:
                break
            if not is_business_day(obs.reference_date):
                # Finais de semana e feriados não geram fatores, mesmo que
                # presentes na série informada.
                continue
            daily_di_factor = compute_daily_di_factor(obs.annual_rate)
            contract_factor = compute_contract_factor(daily_di_factor, percentual)
            raw_factor *= contract_factor
            observations += 1

    return AccumulationResult(
        effective_end_date=effective_end_date,
        observations=observations,
        raw_factor=raw_factor,
        cutoff_reason=cutoff_reason,
    )
