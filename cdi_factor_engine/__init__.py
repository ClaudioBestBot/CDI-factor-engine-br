"""cdi_factor_engine: núcleo auditável de cálculo de CDI percentual e FatorJ.

Este pacote implementa apenas o motor de cálculo (domínio, políticas
decimais, calendário, metodologia e acumulação). Não há coleta automática
de dados, API HTTP, persistência ou integração com terceiros nesta etapa.

A metodologia usada é uma reconstrução própria (não oficial) do cálculo de
FatorJ/CDI percentual, identificada como ``legacy-reconstructed/max-precision-v1``.
Consulte o README para o aviso completo de ausência de afiliação com B3/CETIP.
"""

from .domain.types import FactorJRequest, FactorJResult, RateObservation
from .methodology import METHODOLOGY_VERSION, PRECISION_MODE_MAX
from .use_case import calculate_factor_j
from .validation import (
    DuplicateDateError,
    InternalGapError,
    SeriesValidationError,
    UnsortedSeriesError,
)

__all__ = [
    "FactorJRequest",
    "FactorJResult",
    "RateObservation",
    "METHODOLOGY_VERSION",
    "PRECISION_MODE_MAX",
    "calculate_factor_j",
    "SeriesValidationError",
    "DuplicateDateError",
    "UnsortedSeriesError",
    "InternalGapError",
]

__version__ = "0.1.0"
