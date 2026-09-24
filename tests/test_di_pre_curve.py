"""Synthetic-only tests for MVP 4B."""

from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
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
from cdi_factor_engine.flat_forward import _factor  # internal helper, regression documentation only


SNAPSHOT = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)


def contract(code: str, maturity: date, **kwargs) -> DI1Contract:
    source_mode = kwargs.pop("source_mode", DI1SourceMode.INDICATIVE_INTRADAY_LAST)
    values = dict(
        last_rate=Decimal("10.1234"),
        bid_rate=Decimal("10.10"), ask_rate=Decimal("10.20"),
        previous_settlement_rate=Decimal("10.00"), traded_contracts=100,
        trade_count=20,
    )
    values.update(kwargs)
    return DI1Contract(
        SNAPSHOT, "synthetic-fixture", source_mode,
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


def test_extrapolation_is_opt_in_and_cdi_is_explicit_vertex_at_du_1():
    first = contract("DI1F26", date(2026, 1, 2), last_rate=Decimal("10"))
    second = contract("DI1F27", date(2027, 1, 4), last_rate=Decimal("12"))
    curve = build_di_pre_curve(
        [first, second], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST,
        cdi_rate=Decimal("9.5"), cdi_reference_date=date(2024, 1, 2), cdi_origin="manual-input",
    )
    # DU=0 is only the implicit unit base factor; it never carries a rate.
    with pytest.raises(ValueError):
        curve.get_rate_at_du(0)
    # DU=1 is the CDI's own vertex: exact reproduction, no interpolation.
    assert curve.get_rate_at_du(1) == Decimal("9.5")
    assert curve.vertices[0].origin == "cdi"
    assert curve.vertices[0].du == 1
    assert curve.manifest.vertex_count == 3
    assert curve.manifest.cdi_vertex_du == 1
    assert curve.manifest.period_start == date(2024, 1, 2)
    du_first_di1 = curve.vertices[1].du
    midpoint = (1 + du_first_di1) // 2
    assert 1 < midpoint < du_first_di1
    assert curve.get_rate_at_du(midpoint) == flat_forward_interpolate(
        1, Decimal("9.5"), du_first_di1, curve.vertices[1].rate, midpoint
    )
    with pytest.raises(ValueError):
        curve.get_rate_at_du(curve.vertices[-1][0] + 1)
    assert isinstance(curve.get_rate_at_du(curve.vertices[-1][0] + 1, allow_extrapolation=True), Decimal)


def test_cdi_rate_actually_changes_rates_before_first_di1_vertex():
    """Regression test for the DU=0 mathematical bug.

    Flat Forward's factor is ``(1 + rate/100) ** (DU/252)``; at DU=0 the
    exponent is 0, so ``factor(rate, 0) == 1`` for ANY rate -- the rate is
    algebraically erased. Placing the CDI vertex at DU=0 therefore made the
    interpolated rate between the CDI and the first DI1 vertex completely
    independent of the CDI value, which is mathematically wrong and would
    silently corrupt any curve query in that interval. This test proves the
    corrected DU=1 placement does NOT have this problem, using a hand-rolled
    (non-circular) Decimal computation as the golden value. The complementary
    ``test_du_zero_cannot_carry_a_rate_and_is_rejected_by_flat_forward`` test
    documents the erased-rate defect at its algebraic root.
    """
    du_first_di1 = business_days_between_snapshot_and_maturity(SNAPSHOT.date(), date(2026, 1, 2))
    rate_di1 = Decimal("12")
    target = 10

    def independent_flat_forward(rate_previous: Decimal, du_previous: int) -> Decimal:
        # Hand-rolled replica of the Manual's flat-forward-252 formula,
        # written independently of cdi_factor_engine.flat_forward so the
        # comparison below is not circular/tautological.
        with localcontext() as ctx:
            ctx.prec = 60
            factor_previous = (
                (Decimal(1) + rate_previous / Decimal(100)).ln()
                * (Decimal(du_previous) / Decimal(252))
            ).exp()
            factor_next = (
                (Decimal(1) + rate_di1 / Decimal(100)).ln()
                * (Decimal(du_first_di1) / Decimal(252))
            ).exp()
            weight = Decimal(target - du_previous) / Decimal(du_first_di1 - du_previous)
            factor_target = factor_previous * (
                (factor_next / factor_previous).ln() * weight
            ).exp()
            return (
                (factor_target.ln() * (Decimal(252) / Decimal(target))).exp() - 1
            ) * Decimal(100)

    di1 = contract("DI1F26", date(2026, 1, 2), last_rate=rate_di1)

    def build_with_cdi(cdi_rate: Decimal):
        return build_di_pre_curve(
            [di1], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST,
            cdi_rate=cdi_rate, cdi_reference_date=SNAPSHOT.date(), cdi_origin="manual-input",
        )

    curve_cdi_5 = build_with_cdi(Decimal("5"))
    curve_cdi_10 = build_with_cdi(Decimal("10"))
    du_first = curve_cdi_5.vertices[1].du
    assert du_first == curve_cdi_10.vertices[1].du
    assert 1 < target < du_first

    result_5 = curve_cdi_5.get_rate_at_du(target)
    result_10 = curve_cdi_10.get_rate_at_du(target)
    # Independent, non-circular golden values.
    assert result_5 == independent_flat_forward(Decimal("5"), 1)
    assert result_10 == independent_flat_forward(Decimal("10"), 1)
    # The core assertion of the fix: different CDI rates now produce
    # different curve results before the first DI1 vertex.
    assert result_5 != result_10


def test_du_zero_cannot_carry_a_rate_and_is_rejected_by_flat_forward():
    """Documents the root cause of the DU=0 defect and confirms the guard.

    ``factor(rate, DU) = (1 + rate/100) ** (DU/252)``; at DU=0 the exponent
    is 0, so ``factor(rate, 0) == 1`` for ANY rate -- the rate is erased
    algebraically. This is exactly why a CDI vertex at DU=0 could never
    carry an effective rate, and why ``flat_forward_interpolate`` (reverted
    to its original, pre-MVP-4B behaviour) rejects ``du_previous=0`` or
    ``du_next=0`` outright, rather than silently returning a rate-independent
    result.
    """
    assert _factor(Decimal("5"), 0) == _factor(Decimal("10"), 0) == Decimal(1)
    with pytest.raises(ValueError):
        flat_forward_interpolate(0, Decimal("5"), 21, Decimal("12"), 10)
    with pytest.raises(ValueError):
        flat_forward_interpolate(0, Decimal("10"), 21, Decimal("12"), 10)


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


def test_source_mode_must_match_every_contract():
    item = contract("DI1V26", date(2026, 10, 1))
    build_di_pre_curve([item], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST)
    divergent = contract(
        "DI1V27", date(2027, 10, 1),
        source_mode=DI1SourceMode.PREVIOUS_OFFICIAL_SETTLEMENT,
    )
    with pytest.raises(ValueError, match="DI1V27"):
        build_di_pre_curve(
            [item, divergent], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST
        )


@pytest.mark.parametrize("requested", [["DI1V26"], ["BMF:DI1V26"]])
@pytest.mark.parametrize("received", ["DI1V26", "BMF:DI1V26"])
def test_manual_code_forms_are_canonicalized(requested, received):
    item = contract(received, date(2026, 10, 1))
    curve = build_di_pre_curve(
        [item], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST,
        manual_codes=requested,
    )
    assert curve.manifest.selected_contract_codes == ("DI1V26",)


def test_invalid_or_absent_requested_codes_are_rejected():
    item = contract("DI1V26", date(2026, 10, 1))
    with pytest.raises(DI1FormatError):
        build_di_pre_curve([item], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST,
                           manual_codes=["NOT-A-DI1"])
    with pytest.raises(ValueError, match="absent"):
        build_di_pre_curve([item], source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST,
                           mandatory_codes=["DI1V27"])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"cdi_reference_date": date(2024, 1, 3)}, "reference_date"),
        ({"cdi_origin": " "}, "origin"),
        ({"cdi_rate": Decimal("NaN")}, "cdi_rate"),
        ({"cdi_rate": Decimal("Infinity")}, "cdi_rate"),
        ({"cdi_rate": Decimal("-100")}, "cdi_rate"),
    ],
)
def test_cdi_validation(kwargs, message):
    params = {
        "cdi_rate": Decimal("9.5"),
        "cdi_reference_date": date(2024, 1, 2),
        "cdi_origin": "manual-input",
    }
    params.update(kwargs)
    with pytest.raises(ValueError, match=message):
        build_di_pre_curve(
            [contract("DI1V26", date(2026, 10, 1))],
            source_mode=DI1SourceMode.INDICATIVE_INTRADAY_LAST,
            **params,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("last_rate", Decimal("NaN")),
        ("bid_rate", Decimal("Infinity")),
        ("ask_rate", Decimal("-100")),
        ("previous_settlement_rate", Decimal("-100.01")),
        ("volume", Decimal("-1")),
        ("volume", Decimal("NaN")),
        ("open_interest", -1),
        ("trade_count", -1),
        ("traded_contracts", -1),
    ],
)
def test_di1_numeric_validation(field, value):
    with pytest.raises(DI1FormatError, match=field):
        contract("DI1V26", date(2026, 10, 1), **{field: value})
