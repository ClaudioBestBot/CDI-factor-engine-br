"""Importação local do CSV público de DI-B3; não realiza chamadas de rede."""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from .b3_accumulated import (
    B3AccumulatedError,
    B3RateObservation,
    calculate_b3_daily_rate,
)


class B3CsvImportError(B3AccumulatedError):
    """O CSV B3 não possui o formato ou os valores esperados."""


def _parse_decimal(value: str, field: str) -> Decimal:
    try:
        return Decimal(value.strip().replace(".", "").replace(",", "."))
    except InvalidOperation as error:
        raise B3CsvImportError(f"Valor inválido em {field}: {value!r}") from error


def import_b3_di_csv(path: str | Path) -> list[B3RateObservation]:
    """Lê um CSV B3 UTF-8/BOM local e valida a coluna Fator diário.

    ``Volume financeiro`` e ``Número de operações`` são ignorados; eles não
    participam do cálculo financeiro.
    """

    content = Path(path).read_text(encoding="utf-8-sig")
    if "Nenhum resultado" in content:
        raise B3CsvImportError("CSV B3 informa: Nenhum resultado")

    lines = content.splitlines()
    try:
        header_index = next(
            index
            for index, line in enumerate(lines)
            if line.startswith("Data referência;")
        )
    except StopIteration as error:
        raise B3CsvImportError("Cabeçalho 'Data referência' não encontrado") from error

    reader = csv.DictReader(lines[header_index:], delimiter=";")
    required_columns = {"Data referência", "Média", "Fator diário"}
    if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
        raise B3CsvImportError(
            "CSV B3 deve conter Data referência, Média e Fator diário"
        )

    observations: list[B3RateObservation] = []
    for row in reader:
        if not row or not row.get("Data referência", "").strip():
            continue
        try:
            reference_date = datetime.strptime(
                row["Data referência"].strip(), "%d/%m/%Y"
            ).date()
        except ValueError as error:
            raise B3CsvImportError(
                f"Data referência inválida: {row['Data referência']!r}"
            ) from error

        annual_rate_percent = _parse_decimal(row["Média"], "Média")
        reported_daily_factor = _parse_decimal(row["Fator diário"], "Fator diário")
        calculated_daily_rate = calculate_b3_daily_rate(annual_rate_percent)
        calculated_daily_factor = (Decimal(1) + calculated_daily_rate).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )
        if reported_daily_factor != calculated_daily_factor:
            raise B3CsvImportError(
                "Fator diário divergente em "
                f"{reference_date.isoformat()}: CSV={reported_daily_factor}, "
                f"recalculado={calculated_daily_factor}"
            )
        observations.append(B3RateObservation(reference_date, annual_rate_percent))

    if not observations:
        raise B3CsvImportError("CSV B3 não contém observações")
    return observations
