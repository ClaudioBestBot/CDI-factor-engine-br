"""Synthetic-only tests for MVP 4B."""

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib

import pytest

from cdi_factor_engine import (
    DI1Contract,
    DI1FormatError,
    DI1SourceMode,
    build_di_pre_curve,
    build_di_pre_curve_from_csv,
    business_days_between_snapshot_and_maturity,
    extract_rate,
    first_business_day_of_month,
    flat_forward_interpolate,
    import_di1_csv,
    parse_di1_code,
    rounded_rate_percent,
)


SNAPSHOT = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)


def contract(code: str, maturity: date, **kwargs) -> DI1Contract:
    values = dict(
        last_rate=Decimal("10.1234"),
        bid_rate=Decimal("10.10"), ask_rate=Decimal("10.20"),
        previous_settlement_rate=Decimal("10.00"), traded_contracts=100,
        trade_count=20,
    )
    values.update(kwargs)
    return DI1Contract(
        SNAPSHOT, "synthetic-fixture", DI1SourceMode.INDICATIVE_INTRADAY_LAST,
        code, maturity, **values
    )


def test_parser_covers_all_month_letters_and_bmf_prefix():
    expected = dict(zip("FGHJKMNQUVXZ", range(1, 13)))
    for letter, month in expected.items():
        parsed = parse_di1_code(f"DI1{letter}26")
        assert (parsed.month, parsed.year) == (month, 2026)
    assert parse_di1_code("BMF:DI1V26").month == 10


def test_parser_rejects_maturity_mismatch_and_timezone_is_required():
    with pytest.raises(DI1FormatError):
        parse_di1_code("DI1V26", date(2026, 11, 1))
    with pytest.raises(DI1FormatError):
        DI1Contract(datetime(2024, 1, 2), "x", DI1SourceMode.INDICATIVE_INTRADAY_LAST,
                    "DI1V26", date(2026, 10, 1))


def test_first_business_day_skips_weekend_and_holiday():
    assert first_business_day_of_month(2022, 1) == date(2022, 1, 3)
    assert first_business_day_of_month(2024, 1) == date(2024, 1, 2)


def test_du_convention_is_snapshot_inclusive_and_maturity_exclusive():
    assert business_days_between_snapshot_and_maturity(date(2024, 1, 2), date(2024, 1, 3)) == 1


def test_modes_are_strict_and_mid_requires_two_sides():
    item = contract("DI1V26", date(2026, 10, 1))
    assert extract_rate(item, DI1SourceMode.PREVIOUS_OFFICIAL_SETTLEMENT) == Decimal("10.00")
    assert extract_rate(item, DI1SourceMode.INDICATIVE_INTRADAY_LAST) == Decimal("10.1234")
    assert extract_rate(item, DI1SourceMode.INDICATIVE_INTRADAY_MID) == Decimal("10.15")
    missing_bid = contract("DI1V26", date(2026, 10, 1), bid_rate=None)
    assert extract_rate(missing_bid, DI1SourceMode.INDICATIVE_INTRADAY_MID) is None


def test_missing_rate_is_reported_not_zero():
    item = contract("DI1V26", date(2026, 10, 1), last_rate=None)
    curve = build_di_pre_curve([item], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST)
    report = curve.manifest.selection_reports[0]
    assert report.excluded and report.reason == "missing_rate_for_mode"
    assert report.used_rate is None


def test_manual_and_liquidity_selection_preserve_exclusions():
    good = contract("DI1V26", date(2026, 10, 1), traded_contracts=100, trade_count=10)
    low = contract("DI1V27", date(2027, 10, 1), traded_contracts=1, trade_count=1)
    forced = contract("DI1V28", date(2028, 10, 2), traded_contracts=1, trade_count=1)
    curve = build_di_pre_curve(
        [good, low, forced], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST,
        manual_codes=["DI1V26"], mandatory_codes=["DI1V28"],
        min_traded_contracts=10, min_trade_count=5,
    )
    reasons = {r.contract_code: r.reason for r in curve.manifest.selection_reports}
    assert reasons["DI1V27"] == "not_in_manual_selection"
    assert curve.manifest.selected_contract_codes == ("DI1V26", "DI1V28")
    assert any("low liquidity" in warning for warning in curve.manifest.quality_warnings)


def test_vertices_are_exact_and_interpolation_delegates_to_flat_forward():
    first = contract("DI1F26", date(2026, 1, 2), last_rate=Decimal("10"))
    second = contract("DI1F27", date(2027, 1, 4), last_rate=Decimal("12"))
    curve = build_di_pre_curve([second, first], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST)
    assert curve.get_rate_at_du(curve.vertices[0][0]) == Decimal("10")
    du1, rate1 = curve.vertices[0]
    du2, rate2 = curve.vertices[1]
    target = (du1 + du2) // 2
    assert curve.get_rate_at_du(target) == flat_forward_interpolate(du1, rate1, du2, rate2, target)


def test_extrapolation_is_opt_in_and_cdi_is_explicit_first_vertex():
    first = contract("DI1F26", date(2026, 1, 2), last_rate=Decimal("10"))
    second = contract("DI1F27", date(2027, 1, 4), last_rate=Decimal("12"))
    curve = build_di_pre_curve(
        [first, second], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST,
        cdi_rate=Decimal("9.5"), cdi_reference_date=date(2024, 1, 2), cdi_origin="manual-input",
    )
    assert curve.get_rate_at_du(0) == Decimal("9.5")
    with pytest.raises(ValueError):
        curve.get_rate_at_du(curve.vertices[-1][0] + 1)
    assert isinstance(curve.get_rate_at_du(curve.vertices[-1][0] + 1, allow_extrapolation=True), Decimal)


def test_duplicate_maturity_conflict_is_rejected():
    one = contract("DI1V26", date(2026, 10, 1), last_rate=Decimal("10"))
    two = contract("DI1V26", date(2026, 10, 1), last_rate=Decimal("11"))
    with pytest.raises(ValueError, match="conflicting maturity"):
        build_di_pre_curve([one, two], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST)


def test_presentation_rounding_is_not_internal():
    item = contract("DI1V26", date(2026, 10, 1), last_rate=Decimal("10.12345"))
    curve = build_di_pre_curve([item], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST)
    internal = curve.vertices[0][1]
    assert internal == Decimal("10.12345")
    assert curve.presentation_rate_at_du(curve.vertices[0][0]) == rounded_rate_percent(internal)


def test_csv_import_hash_and_curve_manifest(tmp_path):
    csv_path = tmp_path / "synthetic_di1.csv"
    csv_path.write_text(
        "snapshot_timestamp,source,source_mode,contract_code,maturity_date,last_rate,bid_rate,ask_rate,previous_settlement_rate,open_interest,trade_count,traded_contracts,volume,source_row\n"
        "2024-01-02T15:00:00+00:00,synthetic,indicative_intraday_last,DI1V26,2026-10-01,10.12,,,,,4,10,1000,7\n",
        encoding="utf-8",
    )
    records, digest = import_di1_csv(csv_path)
    assert digest == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    curve = build_di_pre_curve_from_csv(csv_path, source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST)
    assert curve.manifest.source_sha256 == digest
    assert curve.manifest.to_json_dict()["contracts"][0]["contract_code"] == "DI1V26"


def test_curve_rejects_duplicate_du():
    one = contract("DI1V26", date(2026, 10, 1))
    two = contract("DI1V26", date(2026, 10, 1))
    curve = build_di_pre_curve([one, two], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST)
    assert curve.manifest.selection_reports[1].reason == "duplicate_maturity"
