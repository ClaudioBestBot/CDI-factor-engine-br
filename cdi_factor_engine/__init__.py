"""cdi_factor_engine: núcleo auditável de cálculo de CDI percentual e FatorJ.

Este pacote implementa apenas o motor de cálculo (domínio, políticas
decimais, calendário, metodologia e acumulação). Não há coleta automática
de dados, API HTTP, persistência ou integração com terceiros nesta etapa.

O pacote oferece duas metodologias explicitamente selecionáveis:
``legacy-reconstructed/max-precision-v1``, uma reconstrução própria do cálculo
de FatorJ/CDI percentual, e ``b3-accumulated/252-v1``, uma implementação
independente baseada em documentação pública da B3. Nenhuma implica afiliação,
certificação ou endosso da B3/CETIP; consulte o README para os avisos completos.
"""

from .domain.types import FactorJRequest, FactorJResult, RateObservation
from .b3_accumulated import (
    B3_ACCUMULATED_METHODOLOGY_VERSION,
    B3AccumulatedError,
    B3AccumulatedResult,
    B3RateObservation,
    calculate_b3_accumulated,
)
from .b3_csv import B3CsvImportError, import_b3_di_csv
from .b3_history import (
    B3_HISTORY_MANIFEST_VERSION,
    B3_HISTORY_RECORD_VERSION,
    B3HistoryConflictError,
    B3HistoryError,
    B3HistoryFileDigest,
    B3HistoryFormatError,
    B3HistoryManifest,
    B3HistoricalRecord,
    B3HistoryUnsortedError,
    calculate_b3_accumulated_from_history,
    consolidate_b3_history,
    parse_b3_history_csv,
    to_b3_rate_observations,
)
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
    "B3RateObservation",
    "B3AccumulatedResult",
    "METHODOLOGY_VERSION",
    "PRECISION_MODE_MAX",
    "B3_ACCUMULATED_METHODOLOGY_VERSION",
    "calculate_factor_j",
    "calculate_b3_accumulated",
    "import_b3_di_csv",
    "SeriesValidationError",
    "DuplicateDateError",
    "UnsortedSeriesError",
    "InternalGapError",
    "B3AccumulatedError",
    "B3CsvImportError",
    "B3HistoricalRecord",
    "B3HistoryManifest",
    "B3HistoryFileDigest",
    "B3_HISTORY_RECORD_VERSION",
    "B3_HISTORY_MANIFEST_VERSION",
    "B3HistoryError",
    "B3HistoryFormatError",
    "B3HistoryUnsortedError",
    "B3HistoryConflictError",
    "consolidate_b3_history",
    "parse_b3_history_csv",
    "to_b3_rate_observations",
    "calculate_b3_accumulated_from_history",
]

__version__ = "0.1.0"
