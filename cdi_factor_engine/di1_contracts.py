"""Canonical DI1 snapshot records and a deterministic CSV importer.

The CSV schema is UTF-8 (optional BOM), comma-delimited, with the headers
``snapshot_timestamp,source_mode,contract_code,maturity_date,last_rate,
bid_rate,ask_rate,previous_settlement_rate,open_interest,trade_count,
traded_contracts,volume,source_row``. Empty numeric fields are ``None``.
Rates and volume are percentages/quantities represented by ``Decimal``.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
import re


class DI1Error(ValueError):
    """Base error for DI1 snapshot handling."""


class DI1FormatError(DI1Error):
    """Invalid DI1 code, record, or CSV value."""


class DI1SourceMode(str, Enum):
    PREVIOUS_OFFICIAL_SETTLEMENT = "previous_official_settlement"
    INDICATIVE_INTRADAY_LAST = "indicative_intraday_last"
    INDICATIVE_INTRADAY_MID = "indicative_intraday_mid"


@dataclass(frozen=True)
class DI1Code:
    code: str
    month: int
    year: int


_MONTHS = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
           "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
_CODE_RE = re.compile(r"^(?:BMF:)?DI1([FGHJKMNQUVXZ])(\d{2})$", re.IGNORECASE)


def parse_di1_code(code: str, maturity_date: date | None = None) -> DI1Code:
    """Parse ``DI1<month><YY>``; two-digit years are always interpreted as 20YY."""
    normalized = code.strip().upper()
    match = _CODE_RE.fullmatch(normalized)
    if not match:
        raise DI1FormatError(f"invalid DI1 contract code: {code!r}")
    month = _MONTHS[match.group(1)]
    year = 2000 + int(match.group(2))
    parsed = DI1Code(normalized, month, year)
    if maturity_date is not None and (
        maturity_date.month != parsed.month or maturity_date.year != parsed.year
    ):
        raise DI1FormatError(
            f"maturity_date {maturity_date.isoformat()} conflicts with {normalized}"
        )
    return parsed


def _decimal(value: str | None, field: str) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.strip().replace(",", "."))
    except InvalidOperation as exc:
        raise DI1FormatError(f"invalid Decimal in {field}: {value!r}") from exc


def _integer(value: str | None, field: str) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError as exc:
        raise DI1FormatError(f"invalid integer in {field}: {value!r}") from exc


def _date(value: str | None, field: str) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise DI1FormatError(f"invalid date in {field}: {value!r}") from exc


def _timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise DI1FormatError(f"invalid snapshot_timestamp: {value!r}") from exc
    if timestamp.tzinfo is None:
        raise DI1FormatError("snapshot_timestamp must include a timezone")
    return timestamp


@dataclass(frozen=True)
class DI1Contract:
    snapshot_timestamp: datetime
    source: str
    source_mode: DI1SourceMode
    contract_code: str
    maturity_date: date
    last_rate: Decimal | None = None
    bid_rate: Decimal | None = None
    ask_rate: Decimal | None = None
    previous_settlement_rate: Decimal | None = None
    open_interest: int | None = None
    trade_count: int | None = None
    traded_contracts: int | None = None
    volume: Decimal | None = None
    source_row: int | None = None

    def __post_init__(self) -> None:
        if self.snapshot_timestamp.tzinfo is None:
            raise DI1FormatError("snapshot_timestamp must include a timezone")
        parse_di1_code(self.contract_code, self.maturity_date)

    def rate_for_mode(self) -> Decimal | None:
        if self.source_mode is DI1SourceMode.PREVIOUS_OFFICIAL_SETTLEMENT:
            return self.previous_settlement_rate
        if self.source_mode is DI1SourceMode.INDICATIVE_INTRADAY_LAST:
            return self.last_rate
        if self.bid_rate is None or self.ask_rate is None:
            return None
        return (self.bid_rate + self.ask_rate) / Decimal(2)


def extract_rate(contract: DI1Contract, mode: DI1SourceMode | str | None = None) -> Decimal | None:
    """Extract only the rate required by ``mode``; no fallback is performed."""
    selected_mode = DI1SourceMode(mode) if mode is not None else contract.source_mode
    if selected_mode is DI1SourceMode.PREVIOUS_OFFICIAL_SETTLEMENT:
        return contract.previous_settlement_rate
    if selected_mode is DI1SourceMode.INDICATIVE_INTRADAY_LAST:
        return contract.last_rate
    if contract.bid_rate is None or contract.ask_rate is None:
        return None
    return (contract.bid_rate + contract.ask_rate) / Decimal(2)


def import_di1_csv(path: str | Path) -> tuple[list[DI1Contract], str]:
    """Import a local snapshot and return ``(contracts, SHA-256)``."""
    file_path = Path(path)
    raw = file_path.read_bytes()
    records: list[DI1Contract] = []
    with file_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"snapshot_timestamp", "source_mode", "contract_code"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise DI1FormatError(f"CSV must contain headers: {sorted(required)}")
        for row_number, row in enumerate(reader, start=2):
            try:
                mode = DI1SourceMode(row["source_mode"].strip())
            except ValueError as exc:
                raise DI1FormatError(f"invalid source_mode at row {row_number}") from exc
            maturity = _date(row.get("maturity_date"), "maturity_date")
            parsed = parse_di1_code(row["contract_code"], maturity)
            if maturity is None:
                from .di_pre_curve import first_business_day_of_month
                maturity = first_business_day_of_month(parsed.year, parsed.month)
            records.append(DI1Contract(
                snapshot_timestamp=_timestamp(row["snapshot_timestamp"]),
                source=str(row.get("source") or file_path),
                source_mode=mode,
                contract_code=row["contract_code"].strip().upper(),
                maturity_date=maturity,
                last_rate=_decimal(row.get("last_rate"), "last_rate"),
                bid_rate=_decimal(row.get("bid_rate"), "bid_rate"),
                ask_rate=_decimal(row.get("ask_rate"), "ask_rate"),
                previous_settlement_rate=_decimal(row.get("previous_settlement_rate"), "previous_settlement_rate"),
                open_interest=_integer(row.get("open_interest"), "open_interest"),
                trade_count=_integer(row.get("trade_count"), "trade_count"),
                traded_contracts=_integer(row.get("traded_contracts"), "traded_contracts"),
                volume=_decimal(row.get("volume"), "volume"),
                source_row=_integer(row.get("source_row"), "source_row") or row_number,
            ))
    return records, hashlib.sha256(raw).hexdigest()


parse_contract_code = parse_di1_code
DI1ContractRecord = DI1Contract
