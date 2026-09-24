"""Consolidação histórica auditável de séries DI-B3 a partir de múltiplos CSVs.

Este módulo é independente de ``b3_csv.py``/``import_b3_di_csv`` (cujo
contrato público não é alterado) e implementa um registro histórico
canônico (``B3HistoricalRecord``) mais um consolidador de múltiplos
arquivos CSV locais em uma série cronológica única e auditável
(``B3HistoryManifest``).

Regras de consolidação:

- Cada arquivo é lido isoladamente e deve chegar estritamente ordenado por
  data crescente; um arquivo fora de ordem (ou com data repetida dentro
  dele mesmo) **não é reordenado nem deduplicado silenciosamente** — gera
  :class:`B3HistoryUnsortedError`.
- Ao consolidar múltiplos arquivos, um mesmo dia pode aparecer em mais de
  um arquivo somente se o registro for **idêntico** (mesma Média e mesmo
  Fator diário informado); isso é contado como duplicata.
- Um mesmo dia com valores diferentes entre arquivos é um **conflito** e
  interrompe a consolidação com :class:`B3HistoryConflictError` — o
  manifesto auditável (inclusive a lista de conflitos) é anexado à exceção
  para diagnóstico, mas nenhuma série parcial ou "corrigida" é devolvida.
- Lacunas (dias úteis, conforme ``calendar.is_business_day``, sem nenhum
  registro no intervalo coberto) são apenas reportadas no manifesto —
  nunca preenchidas, interpoladas ou inferidas.
- Divergências (registros cujo "Fator diário" informado no CSV não
  confere com o valor recalculado a partir da "Média" publicada, pela
  mesma fórmula de ``b3_accumulated.calculate_b3_daily_rate``) são
  reportadas no manifesto, mas não impedem a consolidação — ao contrário
  de conflitos entre fontes, elas não representam uma contradição
  irreconciliável, e sim um sinal de qualidade a ser auditado pelo
  chamador.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Sequence

from .b3_accumulated import (
    B3AccumulatedError,
    B3AccumulatedResult,
    B3RateObservation,
    calculate_b3_accumulated,
    calculate_b3_daily_rate,
)
from .calendar import is_business_day

#: Versão do esquema do registro histórico canônico.
B3_HISTORY_RECORD_VERSION = "b3-history-record-v1"

#: Versão do esquema do manifesto de consolidação/importação.
B3_HISTORY_MANIFEST_VERSION = "b3-history-manifest-v1"


class B3HistoryError(B3AccumulatedError):
    """Erro base para importação/consolidação do histórico DI-B3."""


class B3HistoryFormatError(B3HistoryError):
    """Um arquivo CSV não possui o formato ou os valores esperados."""


class B3HistoryUnsortedError(B3HistoryError):
    """Um arquivo CSV possui datas fora de ordem estrita ou repetidas.

    A série não é reordenada nem deduplicada silenciosamente.
    """


class B3HistoryConflictError(B3HistoryError):
    """Duas fontes divergem para a mesma data (mesmo dia, valores diferentes)."""

    def __init__(self, message: str, manifest: "B3HistoryManifest") -> None:
        super().__init__(message)
        self.manifest = manifest


@dataclass(frozen=True)
class B3HistoricalRecord:
    """Registro histórico canônico de uma observação DI-B3 Over publicada.

    ``annual_rate_percent`` é a taxa anual DI-B3 Over em percentual (por
    exemplo, ``Decimal("14.90")``), ``reported_daily_factor`` é o "Fator
    diário" exatamente como publicado pela fonte, ``origin`` identifica a
    proveniência do registro (por exemplo, o nome do arquivo CSV de
    origem) e ``version`` identifica a versão deste esquema de registro.
    """

    reference_date: date
    annual_rate_percent: Decimal
    reported_daily_factor: Decimal
    origin: str
    version: str = B3_HISTORY_RECORD_VERSION

    def to_json_dict(self) -> dict[str, str]:
        return {
            "reference_date": self.reference_date.isoformat(),
            "annual_rate_percent": str(self.annual_rate_percent),
            "reported_daily_factor": str(self.reported_daily_factor),
            "origin": self.origin,
            "version": self.version,
        }


@dataclass(frozen=True)
class B3HistoryFileDigest:
    """Metadados auditáveis de um arquivo CSV consolidado."""

    path: str
    sha256: str
    record_count: int

    def to_json_dict(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "record_count": self.record_count,
        }


@dataclass(frozen=True)
class B3HistoryManifest:
    """Manifesto auditável da consolidação de um histórico DI-B3."""

    period_start: date | None
    period_end: date | None
    total_records: int
    duplicate_count: int
    gaps: tuple[date, ...]
    conflicts: tuple[str, ...]
    divergences: tuple[str, ...]
    files: tuple[B3HistoryFileDigest, ...]
    manifest_version: str = B3_HISTORY_MANIFEST_VERSION

    @property
    def gap_count(self) -> int:
        return len(self.gaps)

    @property
    def conflict_count(self) -> int:
        return len(self.conflicts)

    @property
    def divergence_count(self) -> int:
        return len(self.divergences)

    def to_json_dict(self) -> dict:
        return {
            "period_start": self.period_start.isoformat()
            if self.period_start
            else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "total_records": self.total_records,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "gaps": [gap.isoformat() for gap in self.gaps],
            "conflict_count": self.conflict_count,
            "conflicts": list(self.conflicts),
            "divergence_count": self.divergence_count,
            "divergences": list(self.divergences),
            "files": [file_digest.to_json_dict() for file_digest in self.files],
            "manifest_version": self.manifest_version,
        }


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_decimal(value: str, field: str, *, origin: str) -> Decimal:
    try:
        return Decimal(value.strip().replace(".", "").replace(",", "."))
    except InvalidOperation as error:
        raise B3HistoryFormatError(
            f"{origin}: valor inválido em {field}: {value!r}"
        ) from error


def parse_b3_history_csv(path: str | Path) -> list[B3HistoricalRecord]:
    """Lê um único CSV B3 local e devolve registros históricos canônicos.

    Aplica as mesmas convenções de formato do importador legado
    (``import_b3_di_csv``): UTF-8 com BOM, ``;`` como separador, cabeçalho
    após texto introdutório, datas ``DD/MM/YYYY`` e vírgula decimal. Ao
    contrário dele, não rejeita divergências entre "Fator diário" e o
    valor recalculado a partir da "Média" — isso é responsabilidade da
    consolidação (:func:`consolidate_b3_history`), que reporta essas
    divergências no manifesto sem interromper a leitura.

    Rejeita datas fora de ordem estrita ou repetidas dentro do próprio
    arquivo; não reordena nem deduplica silenciosamente.
    """

    file_path = Path(path)
    origin = file_path.name
    content = file_path.read_text(encoding="utf-8-sig")
    if "Nenhum resultado" in content:
        raise B3HistoryFormatError(f"{origin}: CSV B3 informa: Nenhum resultado")

    lines = content.splitlines()
    try:
        header_index = next(
            index
            for index, line in enumerate(lines)
            if line.startswith("Data referência;")
        )
    except StopIteration as error:
        raise B3HistoryFormatError(
            f"{origin}: cabeçalho 'Data referência' não encontrado"
        ) from error

    reader = csv.DictReader(lines[header_index:], delimiter=";")
    required_columns = {"Data referência", "Média", "Fator diário"}
    if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
        raise B3HistoryFormatError(
            f"{origin}: CSV B3 deve conter Data referência, Média e Fator diário"
        )

    records: list[B3HistoricalRecord] = []
    previous_date: date | None = None
    for row in reader:
        if not row or not row.get("Data referência", "").strip():
            continue
        try:
            reference_date = datetime.strptime(
                row["Data referência"].strip(), "%d/%m/%Y"
            ).date()
        except ValueError as error:
            raise B3HistoryFormatError(
                f"{origin}: Data referência inválida: {row['Data referência']!r}"
            ) from error

        if previous_date is not None and reference_date <= previous_date:
            raise B3HistoryUnsortedError(
                f"{origin}: série fora de ordem estrita ou data repetida em "
                f"{reference_date.isoformat()} (anterior: "
                f"{previous_date.isoformat()})"
            )
        previous_date = reference_date

        annual_rate_percent = _parse_decimal(row["Média"], "Média", origin=origin)
        reported_daily_factor = _parse_decimal(
            row["Fator diário"], "Fator diário", origin=origin
        )
        records.append(
            B3HistoricalRecord(
                reference_date=reference_date,
                annual_rate_percent=annual_rate_percent,
                reported_daily_factor=reported_daily_factor,
                origin=origin,
            )
        )

    if not records:
        raise B3HistoryFormatError(f"{origin}: CSV B3 não contém observações")
    return records


def _has_reported_factor_divergence(record: B3HistoricalRecord) -> bool:
    calculated_daily_rate = calculate_b3_daily_rate(record.annual_rate_percent)
    calculated_daily_factor = (Decimal(1) + calculated_daily_rate).quantize(
        Decimal("0.00000001"), rounding=ROUND_HALF_UP
    )
    return record.reported_daily_factor != calculated_daily_factor


def consolidate_b3_history(
    paths: Sequence[str | Path],
) -> tuple[list[B3HistoricalRecord], B3HistoryManifest]:
    """Consolida múltiplos CSVs B3 locais em uma série histórica única.

    Devolve a série consolidada (ordenada cronologicamente, sem
    duplicatas) e o manifesto auditável correspondente. Registros
    idênticos repetidos entre arquivos (mesma data, mesma Média e mesmo
    Fator diário) são contados como duplicatas; registros com a mesma
    data mas valores diferentes entre arquivos interrompem a consolidação
    com :class:`B3HistoryConflictError`, que carrega o manifesto (parcial,
    até o ponto do conflito) no atributo ``manifest`` para diagnóstico.
    Lacunas de dias úteis nunca são preenchidas.
    """

    if not paths:
        raise B3HistoryFormatError("Nenhum arquivo CSV informado para consolidação")

    file_digests: list[B3HistoryFileDigest] = []
    merged: dict[date, B3HistoricalRecord] = {}
    duplicate_count = 0
    conflicts: list[str] = []
    divergences: list[str] = []

    for raw_path in paths:
        file_path = Path(raw_path)
        file_records = parse_b3_history_csv(file_path)
        file_digests.append(
            B3HistoryFileDigest(
                path=str(file_path),
                sha256=_sha256_of_file(file_path),
                record_count=len(file_records),
            )
        )

        for record in file_records:
            if _has_reported_factor_divergence(record):
                divergences.append(
                    f"{record.reference_date.isoformat()} ({record.origin}): "
                    f"Fator diário informado {record.reported_daily_factor} não "
                    "confere com o valor recalculado a partir da Média"
                )

            existing = merged.get(record.reference_date)
            if existing is None:
                merged[record.reference_date] = record
            elif (
                existing.annual_rate_percent == record.annual_rate_percent
                and existing.reported_daily_factor == record.reported_daily_factor
            ):
                duplicate_count += 1
            else:
                conflicts.append(
                    f"{record.reference_date.isoformat()}: "
                    f"{existing.origin} (Média={existing.annual_rate_percent}, "
                    f"Fator diário={existing.reported_daily_factor}) vs "
                    f"{record.origin} (Média={record.annual_rate_percent}, "
                    f"Fator diário={record.reported_daily_factor})"
                )

    ordered_dates = sorted(merged.keys())
    consolidated = [merged[reference_date] for reference_date in ordered_dates]

    gaps: list[date] = []
    if ordered_dates:
        date_set = set(ordered_dates)
        cursor = ordered_dates[0]
        while cursor <= ordered_dates[-1]:
            if cursor not in date_set and is_business_day(cursor):
                gaps.append(cursor)
            cursor += timedelta(days=1)

    manifest = B3HistoryManifest(
        period_start=ordered_dates[0] if ordered_dates else None,
        period_end=ordered_dates[-1] if ordered_dates else None,
        total_records=len(consolidated),
        duplicate_count=duplicate_count,
        gaps=tuple(gaps),
        conflicts=tuple(conflicts),
        divergences=tuple(divergences),
        files=tuple(file_digests),
    )

    if conflicts:
        raise B3HistoryConflictError(
            f"{len(conflicts)} conflito(s) de mesma data com valores "
            "divergentes entre fontes",
            manifest,
        )

    return consolidated, manifest


def to_b3_rate_observations(
    records: Sequence[B3HistoricalRecord],
) -> list[B3RateObservation]:
    """Converte registros históricos canônicos em observações de taxa B3."""

    return [
        B3RateObservation(record.reference_date, record.annual_rate_percent)
        for record in records
    ]


def calculate_b3_accumulated_from_history(
    records: Sequence[B3HistoricalRecord],
    requested_start_date: date,
    requested_end_date: date,
    percentual: Decimal,
    *,
    data_version: str = "b3-history",
) -> B3AccumulatedResult:
    """Calcula o acumulado DI-B3 (``b3-accumulated/252-v1``) a partir do
    histórico consolidado, sem alterar a metodologia existente."""

    return calculate_b3_accumulated(
        to_b3_rate_observations(records),
        requested_start_date,
        requested_end_date,
        percentual,
        data_version=data_version,
    )
