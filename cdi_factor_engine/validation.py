"""Qualidade da série de taxas: duplicatas, ordenação e lacunas internas.

Nenhuma lacuna, duplicidade ou desordenação é preenchida ou ignorada
silenciosamente; qualquer uma delas produz um erro explícito.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

from .calendar import is_business_day
from .domain.types import RateObservation


class SeriesValidationError(ValueError):
    """Erro base para problemas de qualidade na série de taxas."""


class DuplicateDateError(SeriesValidationError):
    """A série contém mais de uma observação para a mesma data."""


class UnsortedSeriesError(SeriesValidationError):
    """A série não está estritamente ordenada por data crescente."""


class InternalGapError(SeriesValidationError):
    """Falta a taxa de um dia útil interno ao intervalo da série."""


def validate_series(observations: Sequence[RateObservation]) -> None:
    """Valida ordenação, duplicidade e lacunas internas em dias úteis.

    Finais de semana e feriados nacionais não são considerados lacunas,
    pois não geram fatores (ver ``calendar.is_business_day``).
    """

    seen: set[date] = set()
    previous: RateObservation | None = None

    for observation in observations:
        current_date = observation.reference_date

        if current_date in seen:
            raise DuplicateDateError(
                f"Data duplicada na série de taxas: {current_date.isoformat()}"
            )
        seen.add(current_date)

        if previous is not None and current_date <= previous.reference_date:
            raise UnsortedSeriesError(
                "Série de taxas desordenada: "
                f"{current_date.isoformat()} não é posterior a "
                f"{previous.reference_date.isoformat()}"
            )

        if previous is not None:
            cursor = previous.reference_date + timedelta(days=1)
            while cursor < current_date:
                if is_business_day(cursor):
                    raise InternalGapError(
                        "Lacuna interna na série de taxas: falta a taxa do "
                        f"dia útil {cursor.isoformat()} entre "
                        f"{previous.reference_date.isoformat()} e "
                        f"{current_date.isoformat()}"
                    )
                cursor += timedelta(days=1)

        previous = observation
