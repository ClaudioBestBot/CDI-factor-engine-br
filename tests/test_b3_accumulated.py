from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cdi_factor_engine import (
    B3AccumulatedError,
    B3CsvImportError,
    B3RateObservation,
    calculate_b3_accumulated,
    import_b3_di_csv,
)
from cdi_factor_engine.b3_accumulated import (
    B3_ACCUMULATED_METHODOLOGY_VERSION,
    calculate_b3_daily_factor,
    calculate_b3_daily_rate,
)


def test_b3_includes_start_and_excludes_end():
    start = date(2025, 9, 24)
    end = date(2025, 9, 25)
    result = calculate_b3_accumulated(
        [
            B3RateObservation(start, Decimal("14.90")),
            B3RateObservation(end, Decimal("99.99")),
        ],
        start,
        end,
        Decimal("100.0000"),
    )
    assert result.observations == 1
    assert result.accumulated_factor_trunc16 == calculate_b3_daily_factor(
        Decimal("14.90"), Decimal("100.0000")
    )
    assert result.methodology_version == B3_ACCUMULATED_METHODOLOGY_VERSION
    assert result.to_json_dict()["temporal_convention"] == "[start_date, end_date)"


def test_b3_daily_rate_rounds_to_eight_places_and_factor_truncates_to_sixteen():
    daily_rate = calculate_b3_daily_rate(Decimal("14.90"))
    daily_factor = calculate_b3_daily_factor(Decimal("14.90"), Decimal("114.0000"))
    assert daily_rate.as_tuple().exponent == -8
    assert daily_factor.as_tuple().exponent == -16


def test_b3_percentual_requires_at_most_four_decimal_places():
    with pytest.raises(B3AccumulatedError, match="quatro casas"):
        calculate_b3_accumulated(
            [B3RateObservation(date(2025, 9, 24), Decimal("14.90"))],
            date(2025, 9, 24),
            date(2025, 9, 25),
            Decimal("114.00001"),
        )


def test_b3_truncates_accumulation_after_every_multiplication():
    rates = [
        B3RateObservation(date(2025, 9, 24), Decimal("14.90")),
        B3RateObservation(date(2025, 9, 25), Decimal("14.91")),
    ]
    result = calculate_b3_accumulated(
        rates, date(2025, 9, 24), date(2025, 9, 26), Decimal("114.0000")
    )
    expected = Decimal(1)
    for rate in rates:
        expected = (expected * calculate_b3_daily_factor(rate.annual_rate_percent, Decimal("114.0000"))).quantize(
            Decimal("0.0000000000000001"), rounding="ROUND_DOWN"
        )
    assert result.accumulated_factor_trunc16 == expected
    assert result.final_factor_round8 == expected.quantize(
        Decimal("0.00000001"), rounding="ROUND_HALF_UP"
    )


def test_b3_constant_249_observations_matches_official_example():
    observations = [
        B3RateObservation(date(2025, 1, 1).fromordinal(date(2025, 1, 1).toordinal() + index), Decimal("6.40"))
        for index in range(249)
    ]
    result = calculate_b3_accumulated(
        observations,
        observations[0].reference_date,
        date(2025, 1, 1).fromordinal(observations[-1].reference_date.toordinal() + 1),
        Decimal("114.0000"),
    )
    assert result.final_factor_round8 == Decimal("1.07237576")
    assert (Decimal("120000.00") * result.final_factor_round8).quantize(
        Decimal("0.01")
    ) == Decimal("128685.09")


def test_b3_csv_importer_reads_local_format_and_validates_daily_rate(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "\ufeffTexto introdutório\nData referência;Média;Fator diário;Volume financeiro\n"
        "24/09/2025;14,90;1,00055131;-\n",
        encoding="utf-8",
    )
    assert import_b3_di_csv(csv_path) == [
        B3RateObservation(date(2025, 9, 24), Decimal("14.90"))
    ]


def test_b3_csv_importer_rejects_no_results_and_daily_rate_mismatch(tmp_path):
    empty_path = tmp_path / "empty.csv"
    empty_path.write_text("\ufeffNenhum resultado", encoding="utf-8")
    with pytest.raises(B3CsvImportError, match="Nenhum resultado"):
        import_b3_di_csv(empty_path)

    invalid_path = tmp_path / "invalid.csv"
    invalid_path.write_text(
        "\ufeffData referência;Média;Fator diário\n24/09/2025;14,90;0,00000000\n",
        encoding="utf-8",
    )
    with pytest.raises(B3CsvImportError, match="divergente"):
        import_b3_di_csv(invalid_path)


LOCAL_B3_CSV = Path(__file__).parents[1] / "local-data" / "DI over-24-09-2025.csv"


@pytest.mark.skipif(
    not LOCAL_B3_CSV.exists(),
    reason="fixture anual B3 local não publicado neste repositório",
)
def test_b3_official_local_annual_fixture():
    observations = import_b3_di_csv(LOCAL_B3_CSV)
    assert len(observations) == 251
    assert observations[0].reference_date == date(2025, 9, 24)
    assert observations[-1].reference_date == date(2026, 9, 23)

    for percentual, expected in (
        (Decimal("100.0000"), Decimal("1.14498907")),
        (Decimal("114.0000"), Decimal("1.16689290")),
    ):
        result = calculate_b3_accumulated(
            observations,
            date(2025, 9, 24),
            date(2026, 9, 24),
            percentual,
            data_version="local-b3-fixture",
        )
        assert result.observations == 251
        assert result.final_factor_round8 == expected
