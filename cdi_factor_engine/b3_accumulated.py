"""Metodologia acumulada DI-B3, independente do cálculo legado de FatorJ."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, localcontext
from typing import Sequence

B3_ACCUMULATED_METHODOLOGY_VERSION = "b3-accumulated/252-v1"
B3_ACCUMULATED_TEMPORAL_CONVENTION = "[start_date, end_date)"
B3_ACCUMULATED_PRECISION_MODE = (
    "tdi-round-half-up-8/daily-and-accumulated-truncate-16/final-round-half-up-8"
)
B3_ANNUALIZATION_BASE = Decimal(252)


class B3AccumulatedError(ValueError):
    """Erro de entrada para a metodologia acumulada DI-B3."""


@dataclass(frozen=True)
class B3RateObservation:
    """Taxa DI-B3 Over anual, em percentual (por exemplo, ``14.90``)."""

    reference_date: date
    annual_rate_percent: Decimal


@dataclass(frozen=True)
class B3AccumulatedResult:
    """Resultado auditável do acumulado DI-B3."""

    requested_start_date: date
    requested_end_date: date
    observations: int
    accumulated_factor_trunc16: Decimal
    final_factor_round8: Decimal
    methodology_version: str
    temporal_convention: str
    precision_mode: str
    data_version: str

    def to_json_dict(self) -> dict[str, str | int]:
        return {
            "requested_start_date": self.requested_start_date.isoformat(),
            "requested_end_date": self.requested_end_date.isoformat(),
            "observations": self.observations,
            "accumulated_factor_trunc16": str(self.accumulated_factor_trunc16),
            "final_factor_round8": str(self.final_factor_round8),
            "methodology_version": self.methodology_version,
            "temporal_convention": self.temporal_convention,
            "precision_mode": self.precision_mode,
            "data_version": self.data_version,
        }


def _quantum(places: int) -> Decimal:
    return Decimal(1).scaleb(-places)


def _truncate(value: Decimal, places: int) -> Decimal:
    return value.quantize(_quantum(places), rounding=ROUND_DOWN)


def _round_half_up(value: Decimal, places: int) -> Decimal:
    return value.quantize(_quantum(places), rounding=ROUND_HALF_UP)


def calculate_b3_daily_rate(annual_rate_percent: Decimal) -> Decimal:
    """Calcula TDIk, arredondada em oito casas conforme a metodologia B3."""

    with localcontext() as context:
        context.prec = 60
        daily_rate = (
            (Decimal(1) + annual_rate_percent / Decimal(100))
            ** (Decimal(1) / B3_ANNUALIZATION_BASE)
            - Decimal(1)
        )
        return _round_half_up(daily_rate, 8)


def calculate_b3_daily_factor(
    annual_rate_percent: Decimal, percentual: Decimal
) -> Decimal:
    """Calcula o fator diário truncado em dezesseis casas."""

    daily_rate = calculate_b3_daily_rate(annual_rate_percent)
    return _truncate(Decimal(1) + daily_rate * (percentual / Decimal(100)), 16)


def _validate_percentual(percentual: Decimal) -> None:
    if percentual.as_tuple().exponent < -4:
        raise B3AccumulatedError("percentual deve ter no máximo quatro casas decimais")


def _validate_series(rate_series: Sequence[B3RateObservation]) -> None:
    previous_date: date | None = None
    for observation in rate_series:
        if previous_date is not None and observation.reference_date <= previous_date:
            raise B3AccumulatedError(
                "A série B3 deve estar estritamente ordenada e sem datas duplicadas"
            )
        previous_date = observation.reference_date


def calculate_b3_accumulated(
    rate_series: Sequence[B3RateObservation],
    requested_start_date: date,
    requested_end_date: date,
    percentual: Decimal,
    *,
    data_version: str = "unspecified",
) -> B3AccumulatedResult:
    """Calcula DI-B3 acumulado no intervalo ``[start_date, end_date)``.

    Este caminho não aplica calendário aproximado nem o recuo da data final
    da metodologia legada: somente as observações fornecidas no intervalo
    explícito são remuneradas.
    """

    if requested_start_date > requested_end_date:
        raise B3AccumulatedError(
            "requested_start_date não pode ser posterior a requested_end_date"
        )
    _validate_percentual(percentual)
    _validate_series(rate_series)

    accumulated = Decimal(1)
    observations = 0
    with localcontext() as context:
        context.prec = 60
        for observation in rate_series:
            if observation.reference_date < requested_start_date:
                continue
            if observation.reference_date >= requested_end_date:
                break
            accumulated = _truncate(
                accumulated
                * calculate_b3_daily_factor(
                    observation.annual_rate_percent, percentual
                ),
                16,
            )
            observations += 1

    return B3AccumulatedResult(
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        observations=observations,
        accumulated_factor_trunc16=accumulated,
        final_factor_round8=_round_half_up(accumulated, 8),
        methodology_version=B3_ACCUMULATED_METHODOLOGY_VERSION,
        temporal_convention=B3_ACCUMULATED_TEMPORAL_CONVENTION,
        precision_mode=B3_ACCUMULATED_PRECISION_MODE,
        data_version=data_version,
    )
