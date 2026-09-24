"""Auditable DI1 DI x PRE curve construction using ANBIMA and Flat Forward."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable

from .anbima_calendar import (
    ALGORITHMIC_CALENDAR_VERSION,
    AnbimaCalendar,
    is_anbima_business_day,
)
from .di1_contracts import DI1Contract, DI1SourceMode, extract_rate, import_di1_csv
from .flat_forward import (
    flat_forward_extrapolate_curve,
    flat_forward_interpolate,
    rounded_rate_percent,
)

DI_PRE_CURVE_METHODOLOGY_VERSION = "di-pre-curve/v1"


def first_business_day_of_month(
    year: int, month: int, calendar: AnbimaCalendar | None = None
) -> date:
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    current = date(year, month, 1)
    while not is_anbima_business_day(current, calendar):
        current += timedelta(days=1)
    return current


def business_days_between_snapshot_and_maturity(
    snapshot_date: date, maturity_date: date, calendar: AnbimaCalendar | None = None
) -> int:
    """Count ANBIMA business days in ``[snapshot_date, maturity_date)``."""
    if maturity_date < snapshot_date:
        raise ValueError("maturity_date cannot precede snapshot_date")
    current, count = snapshot_date, 0
    while current < maturity_date:
        if is_anbima_business_day(current, calendar):
            count += 1
        current += timedelta(days=1)
    return count


@dataclass(frozen=True)
class CDIReference:
    rate: Decimal
    reference_date: date
    origin: str


@dataclass(frozen=True)
class DI1SelectionReport:
    contract_code: str
    selected: bool
    excluded: bool
    reason: str | None
    traded_contracts: int | None
    trade_count: int | None
    used_rate: Decimal | None
    source_mode: DI1SourceMode
    maturity_date: date
    du: int | None

    def to_json_dict(self) -> dict:
        return {
            "contract_code": self.contract_code,
            "selected": self.selected,
            "excluded": self.excluded,
            "reason": self.reason,
            "traded_contracts": self.traded_contracts,
            "trade_count": self.trade_count,
            "used_rate": str(self.used_rate) if self.used_rate is not None else None,
            "source_mode": self.source_mode.value,
            "maturity_date": self.maturity_date.isoformat(),
            "du": self.du,
        }


@dataclass(frozen=True)
class DI1CurveManifest:
    methodology_version: str
    calendar_version: str
    snapshot_timestamp: datetime
    snapshot_source: str
    source_mode: DI1SourceMode
    cdi: CDIReference | None
    total_contracts_received: int
    selected_contract_codes: tuple[str, ...]
    excluded_contracts: tuple[dict, ...]
    first_maturity_date: date | None
    last_maturity_date: date | None
    vertex_count: int
    period_start: date | None
    period_end: date | None
    source_sha256: str | None
    quality_warnings: tuple[str, ...]
    curve_kind: str
    selection_reports: tuple[DI1SelectionReport, ...]

    def to_json_dict(self) -> dict:
        return {
            "methodology_version": self.methodology_version,
            "calendar_version": self.calendar_version,
            "snapshot_timestamp": self.snapshot_timestamp.isoformat(),
            "snapshot_source": self.snapshot_source,
            "source_mode": self.source_mode.value,
            "cdi": None if self.cdi is None else {
                "rate": str(self.cdi.rate),
                "reference_date": self.cdi.reference_date.isoformat(),
                "origin": self.cdi.origin,
            },
            "total_contracts_received": self.total_contracts_received,
            "selected_contract_codes": list(self.selected_contract_codes),
            "excluded_contracts": list(self.excluded_contracts),
            "first_maturity_date": self.first_maturity_date.isoformat() if self.first_maturity_date else None,
            "last_maturity_date": self.last_maturity_date.isoformat() if self.last_maturity_date else None,
            "vertex_count": self.vertex_count,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "source_sha256": self.source_sha256,
            "quality_warnings": list(self.quality_warnings),
            "curve_kind": self.curve_kind,
            "contracts": [item.to_json_dict() for item in self.selection_reports],
        }


@dataclass(frozen=True)
class DI1Curve:
    vertices: tuple[tuple[int, Decimal], ...]
    vertex_contracts: tuple[DI1Contract, ...]
    manifest: DI1CurveManifest
    cdi: CDIReference | None = None

    def get_rate_at_du(self, du: int, *, allow_extrapolation: bool = False) -> Decimal:
        if du < 0:
            raise ValueError("DU must not be negative")
        if self.cdi is not None and du == 0:
            return self.cdi.rate
        for vertex_du, rate in self.vertices:
            if du == vertex_du:
                return rate
        if not self.vertices:
            raise ValueError("curve has no DI1 vertices")
        if du < self.vertices[0][0]:
            raise ValueError("DU is before the first DI1 vertex")
        for previous, following in zip(self.vertices, self.vertices[1:]):
            if previous[0] < du < following[0]:
                return flat_forward_interpolate(previous[0], previous[1], following[0], following[1], du)
        if not allow_extrapolation:
            raise ValueError("DU is after the last vertex; extrapolation is disabled")
        return flat_forward_extrapolate_curve(self.vertices, du)

    def presentation_rate_at_du(self, du: int, *, allow_extrapolation: bool = False) -> Decimal:
        return rounded_rate_percent(self.get_rate_at_du(du, allow_extrapolation=allow_extrapolation))

    @property
    def rates(self) -> tuple[Decimal, ...]:
        return tuple(rate for _, rate in self.vertices)


def build_di_pre_curve(
    contracts: Iterable[DI1Contract],
    *,
    source_mode: DI1SourceMode | str,
    cdi_rate: Decimal | None = None,
    cdi_reference_date: date | None = None,
    cdi_origin: str | None = None,
    manual_codes: Iterable[str] | None = None,
    mandatory_codes: Iterable[str] = (),
    min_traded_contracts: int | None = None,
    min_trade_count: int | None = None,
    calendar: AnbimaCalendar | None = None,
    source_sha256: str | None = None,
    snapshot_source: str | None = None,
) -> DI1Curve:
    mode = DI1SourceMode(source_mode)
    records = tuple(contracts)
    if not records:
        raise ValueError("at least one DI1 contract is required")
    snapshot = records[0].snapshot_timestamp
    if snapshot.tzinfo is None:
        raise ValueError("snapshot_timestamp must include a timezone")
    if any(record.snapshot_timestamp != snapshot for record in records):
        raise ValueError("all contracts must belong to the same snapshot")
    if cdi_rate is not None and (cdi_reference_date is None or cdi_origin is None):
        raise ValueError("cdi_reference_date and cdi_origin are required with cdi_rate")
    cdi = None if cdi_rate is None else CDIReference(cdi_rate, cdi_reference_date, cdi_origin)
    manual = {code.strip().upper() for code in manual_codes} if manual_codes is not None else None
    mandatory = {code.strip().upper() for code in mandatory_codes}
    reports: list[DI1SelectionReport] = []
    selected_pairs: list[tuple[DI1Contract, int, Decimal]] = []
    seen_maturities: dict[date, tuple[Decimal, str]] = {}
    for record in records:
        code = record.contract_code.upper()
        du = business_days_between_snapshot_and_maturity(snapshot.date(), record.maturity_date, calendar)
        rate = extract_rate(record, mode)
        reason = None
        forced = code in mandatory
        if rate is None:
            reason = "missing_rate_for_mode"
        elif manual is not None and code not in manual and not forced:
            reason = "not_in_manual_selection"
        elif min_traded_contracts is not None and not forced and (
            record.traded_contracts is None or record.traded_contracts < min_traded_contracts
        ):
            reason = "below_min_traded_contracts"
        elif min_trade_count is not None and not forced and (
            record.trade_count is None or record.trade_count < min_trade_count
        ):
            reason = "below_min_trade_count"
        elif record.maturity_date in seen_maturities:
            previous_rate, previous_code = seen_maturities[record.maturity_date]
            if previous_rate != rate:
                raise ValueError(f"conflicting maturity {record.maturity_date}: {previous_code} and {code}")
            reason = "duplicate_maturity"
        selected = reason is None
        if selected:
            seen_maturities[record.maturity_date] = (rate, code)
            selected_pairs.append((record, du, rate))
        reports.append(DI1SelectionReport(code, selected, not selected, reason, record.traded_contracts, record.trade_count, rate, mode, record.maturity_date, du))
    selected_pairs.sort(key=lambda item: item[1])
    dus = [item[1] for item in selected_pairs]
    if len(dus) != len(set(dus)):
        raise ValueError("duplicate DU among selected vertices")
    vertices = tuple((du, rate) for _, du, rate in selected_pairs)
    warnings = tuple(
        f"{report.contract_code}: low liquidity but included manually"
        for report in reports
        if report.selected and report.contract_code in mandatory
        and ((min_traded_contracts is not None and (report.traded_contracts is None or report.traded_contracts < min_traded_contracts))
             or (min_trade_count is not None and (report.trade_count is None or report.trade_count < min_trade_count)))
    )
    manifest = DI1CurveManifest(
        DI_PRE_CURVE_METHODOLOGY_VERSION,
        calendar.version if calendar else ALGORITHMIC_CALENDAR_VERSION,
        snapshot,
        snapshot_source or records[0].source,
        mode,
        cdi,
        len(records),
        tuple(record.contract_code for record, _, _ in selected_pairs),
        tuple(report.to_json_dict() for report in reports if report.excluded),
        selected_pairs[0][0].maturity_date if selected_pairs else None,
        selected_pairs[-1][0].maturity_date if selected_pairs else None,
        len(vertices) + (1 if cdi else 0),
        selected_pairs[0][0].maturity_date if selected_pairs else None,
        selected_pairs[-1][0].maturity_date if selected_pairs else None,
        source_sha256,
        warnings,
        "ajuste oficial anterior" if mode is DI1SourceMode.PREVIOUS_OFFICIAL_SETTLEMENT else "indicativa intradiária",
        tuple(reports),
    )
    return DI1Curve(vertices, tuple(record for record, _, _ in selected_pairs), manifest, cdi)


build_curve = build_di_pre_curve


def build_di_pre_curve_from_csv(
    path: str,
    *,
    source_mode: DI1SourceMode | str,
    **kwargs,
) -> DI1Curve:
    """Import a local snapshot, retain its digest, and build the curve."""
    contracts, digest = import_di1_csv(path)
    return build_di_pre_curve(
        contracts,
        source_mode=source_mode,
        source_sha256=digest,
        snapshot_source=path,
        **kwargs,
    )
