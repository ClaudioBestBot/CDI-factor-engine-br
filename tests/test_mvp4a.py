from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cdi_factor_engine import (
    ANBIMA_ALGORITHMIC_CALENDAR_VERSION,
    ANBIMA_IMPORTED_CALENDAR_VERSION,
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
    assert calendar.version == ANBIMA_ALGORITHMIC_CALENDAR_VERSION
    assert ANBIMA_CALENDAR_VERSION == ANBIMA_ALGORITHMIC_CALENDAR_VERSION
    assert calendar.period_start == date(2001, 1, 1)
    assert calendar.period_end == date(2099, 12, 31)
    assert is_anbima_business_day(date(2026, 12, 31))
    assert not is_anbima_business_day(date(2027, 1, 1))
    assert is_anbima_business_day(date(2023, 11, 20))
    assert not is_anbima_business_day(date(2024, 11, 20))


def test_generated_calendar_consolidates_real_collision():
    calendar = generate_anbima_calendar()
    holiday = next(item for item in calendar.holidays if item.reference_date == date(2079, 4, 21))
    assert len(holiday.names) >= 2
    assert "Tiradentes" in holiday.names
    assert "Sexta-feira Santa" in holiday.names


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
    assert calendar.version == ANBIMA_IMPORTED_CALENDAR_VERSION
    assert calendar.raw_rows_processed == 2


def test_import_fixture_ignores_documentary_footer(tmp_path):
    fixture = tmp_path / "holidays-with-footer.csv"
    fixture.write_text(
        "Data;Dia da Semana;Feriado\n"
        "01/01/2024;segunda-feira;Confraternização Universal\n"
        "Fonte: calendário público;;;;\n"
        "01/01/2025;quarta-feira;Não deve ser processado\n",
        encoding="utf-8",
    )
    calendar = import_anbima_holidays_csv_fixture(fixture)
    assert calendar.raw_rows_processed == 1
    assert calendar.ignored_footer_start_row == 3
    assert date(2025, 1, 1) not in calendar.dates


def test_flat_forward_manual_examples():
    # Golden values calculated independently outside this implementation with
    # the item 1.4.2 accumulated-factor formula.
    expected = Decimal("11.565091662757372735")
    actual = flat_forward_interpolate(100, Decimal("5"), 200, Decimal("15"), 150)
    assert abs(actual - expected) < Decimal("1E-9")

    # The same independently calculated golden formula, extrapolated with the
    # implicit forward from DU 100 to DU 200.
    expected = Decimal("18.540663597328139425")
    actual = flat_forward_extrapolate(100, Decimal("5"), 200, Decimal("15"), 300)
    assert abs(actual - expected) < Decimal("1E-9")
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
    assert flat_forward_interpolate(10, Decimal("10"), 20, Decimal("20"), 10) == Decimal("10")
    assert flat_forward_interpolate(10, Decimal("10"), 20, Decimal("20"), 20) == Decimal("20")
    assert rounded_rate_percent(Decimal("12.3456")) == Decimal("12.346")


OFFICIAL_XLS = Path("local-data/feriados_nacionais.xls")


@pytest.mark.skipif(not OFFICIAL_XLS.exists(), reason="official local holiday workbook is not available")
def test_official_anbima_workbook_is_auditable():
    """Validates the user's local workbook; skipped when it is not provided."""

    from cdi_factor_engine import import_anbima_holidays_xls

    calendar = import_anbima_holidays_xls(OFFICIAL_XLS)
    assert calendar.sha256
    assert len(calendar.dates) == 1263
    assert calendar.raw_rows_processed == 1264
    collision = next(item for item in calendar.holidays if item.reference_date == date(2079, 4, 21))
    assert len(collision.names) >= 2
