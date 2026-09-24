from datetime import date
from decimal import Decimal

import pytest

from cdi_factor_engine import (
    ANBIMA_CALENDAR_VERSION,
    flat_forward_extrapolate,
    flat_forward_extrapolate_curve,
    flat_forward_interpolate,
    generate_anbima_calendar,
    import_anbima_holidays_csv_fixture,
    is_anbima_business_day,
    rounded_rate_percent,
)


def test_anbima_calendar_is_independent_and_explicit():
    calendar = generate_anbima_calendar()
    assert calendar.version == ANBIMA_CALENDAR_VERSION
    assert calendar.period_start == date(2001, 1, 1)
    assert calendar.period_end == date(2099, 12, 31)
    assert is_anbima_business_day(date(2026, 12, 31))
    assert not is_anbima_business_day(date(2027, 1, 1))


def test_duplicate_holidays_keep_all_names(tmp_path):
    fixture = tmp_path / "holidays.csv"
    fixture.write_text(
        "Data;Dia da Semana;Feriado\n"
        "21/04/2079;sexta-feira;Tiradentes\n"
        "21/04/2079;sexta-feira;Sexta-feira Santa\n",
        encoding="utf-8",
    )
    calendar = import_anbima_holidays_csv_fixture(fixture)
    assert len(calendar.holidays) == 1
    assert calendar.holidays[0].names == ("Tiradentes", "Sexta-feira Santa")
    assert calendar.sha256


def test_flat_forward_manual_examples():
    # DU 0/252, 10%/20%: fator alvo em DU 126 = sqrt(1.10*1.20).
    expected = (Decimal("1.10") * Decimal("1.20")).sqrt() * 100 - 100
    actual = flat_forward_interpolate(0, Decimal("10"), 252, Decimal("20"), 126)
    assert abs(actual - expected) < Decimal("0.0000000000000000001")

    # DU 100/200, 5%/15%, alvo 150: fator = 1.05*(1.15/1.05)^0.5.
    expected = Decimal("1.05") * (Decimal("1.15") / Decimal("1.05")).sqrt() * 100 - 100
    actual = flat_forward_interpolate(100, Decimal("5"), 200, Decimal("15"), 150)
    assert abs(actual - expected) < Decimal("0.0000000000000000001")

    # Extrapolação de 100/200 a 300 mantém o mesmo forward implícito.
    expected = Decimal("1.05") * (Decimal("1.15") / Decimal("1.05")) ** Decimal("2") * 100 - 100
    actual = flat_forward_extrapolate(100, Decimal("5"), 200, Decimal("15"), 300)
    assert abs(actual - expected) < Decimal("0.0000000000000000001")
    assert flat_forward_extrapolate_curve(
        [(0, Decimal("1")), (100, Decimal("5")), (200, Decimal("15"))], 300
    ) == actual


def test_flat_forward_validation_and_presentation():
    with pytest.raises(ValueError):
        flat_forward_interpolate(2, Decimal("1"), 2, Decimal("2"), 2)
    with pytest.raises(ValueError):
        flat_forward_interpolate(0, Decimal("-100"), 1, Decimal("2"), 1)
    with pytest.raises(ValueError):
        flat_forward_interpolate(0, Decimal("1"), 10, Decimal("2"), 11)
    assert flat_forward_interpolate(0, Decimal("10"), 10, Decimal("20"), 0) == Decimal("10")
    assert flat_forward_interpolate(0, Decimal("10"), 10, Decimal("20"), 10) == Decimal("20")
    assert rounded_rate_percent(Decimal("12.3456")) == Decimal("12.346")
