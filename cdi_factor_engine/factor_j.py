"""Cálculo do FatorJ contratado: acumulação + truncagem operacional."""

from __future__ import annotations

from decimal import Decimal

from .accumulator import accumulate
from .calendar import CALENDAR_VERSION
from .decimal_policy import truncate
from .domain.types import FactorJRequest, FactorJResult
from .methodology import PRECISION_MODE_MAX


def calculate(request: FactorJRequest) -> FactorJResult:
    """Calcula o FatorJ para a requisição informada.

    Não aplica arredondamento intermediário diário; a truncagem em seis
    casas decimais ocorre apenas no fator operacional final.
    """

    result = accumulate(
        rate_series=request.rate_series,
        requested_start_date=request.requested_start_date,
        requested_end_date=request.requested_end_date,
        percentual=request.percentual,
    )

    operational_factor = truncate(result.raw_factor)

    return FactorJResult(
        requested_start_date=request.requested_start_date,
        requested_end_date=request.requested_end_date,
        effective_end_date=result.effective_end_date,
        observations=result.observations,
        raw_factor=result.raw_factor,
        operational_factor_trunc6=operational_factor,
        cutoff_reason=result.cutoff_reason,
        precision_mode=PRECISION_MODE_MAX,
        methodology_version=request.methodology_version,
        data_version=request.data_version,
        calendar_version=CALENDAR_VERSION,
    )
