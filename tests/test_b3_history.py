import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cdi_factor_engine import (
    B3_HISTORY_RECORD_VERSION,
    B3HistoricalRecord,
    B3HistoryConflictError,
    B3HistoryFormatError,
    B3HistoryUnsortedError,
    calculate_b3_accumulated_from_history,
    consolidate_b3_history,
    parse_b3_history_csv,
    to_b3_rate_observations,
)
from cdi_factor_engine.b3_accumulated import (
    B3RateObservation,
    calculate_b3_accumulated,
)


def _write_csv(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    lines = ["\ufeffTexto introdutório", "Data referência;Média;Fator diário;Volume financeiro"]
    for reference_date, media, fator in rows:
        lines.append(f"{reference_date};{media};{fator};-")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_parse_b3_history_csv_returns_canonical_records(tmp_path):
    csv_path = _write_csv(
        tmp_path / "day1.csv", [("24/09/2025", "14,90", "1,00055131")]
    )
    records = parse_b3_history_csv(csv_path)
    assert records == [
        B3HistoricalRecord(
            reference_date=date(2025, 9, 24),
            annual_rate_percent=Decimal("14.90"),
            reported_daily_factor=Decimal("1.00055131"),
            origin="day1.csv",
        )
    ]
    assert records[0].version == B3_HISTORY_RECORD_VERSION


def test_parse_b3_history_csv_rejects_unsorted_rows_without_reordering(tmp_path):
    csv_path = _write_csv(
        tmp_path / "unsorted.csv",
        [
            ("25/09/2025", "14,91", "1,00055211"),
            ("24/09/2025", "14,90", "1,00055131"),
        ],
    )
    with pytest.raises(B3HistoryUnsortedError, match="fora de ordem"):
        parse_b3_history_csv(csv_path)


def test_parse_b3_history_csv_rejects_repeated_date_within_same_file(tmp_path):
    csv_path = _write_csv(
        tmp_path / "repeated.csv",
        [
            ("24/09/2025", "14,90", "1,00055131"),
            ("24/09/2025", "14,90", "1,00055131"),
        ],
    )
    with pytest.raises(B3HistoryUnsortedError):
        parse_b3_history_csv(csv_path)


def test_parse_b3_history_csv_rejects_no_results(tmp_path):
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("\ufeffNenhum resultado", encoding="utf-8")
    with pytest.raises(B3HistoryFormatError, match="Nenhum resultado"):
        parse_b3_history_csv(csv_path)


def test_consolidate_merges_multiple_files_chronologically_with_sha256(tmp_path):
    file1 = _write_csv(
        tmp_path / "part1.csv",
        [
            ("24/09/2025", "14,90", "1,00055131"),
            ("25/09/2025", "14,90", "1,00055131"),
        ],
    )
    file2 = _write_csv(
        tmp_path / "part2.csv",
        [
            ("26/09/2025", "14,91", "1,00055211"),
        ],
    )

    records, manifest = consolidate_b3_history([file1, file2])

    assert [record.reference_date for record in records] == [
        date(2025, 9, 24),
        date(2025, 9, 25),
        date(2025, 9, 26),
    ]
    assert manifest.period_start == date(2025, 9, 24)
    assert manifest.period_end == date(2025, 9, 26)
    assert manifest.total_records == 3
    assert manifest.duplicate_count == 0
    assert manifest.conflicts == ()
    assert manifest.gap_count == 0

    assert len(manifest.files) == 2
    expected_sha1 = hashlib.sha256(file1.read_bytes()).hexdigest()
    expected_sha2 = hashlib.sha256(file2.read_bytes()).hexdigest()
    assert manifest.files[0].sha256 == expected_sha1
    assert manifest.files[1].sha256 == expected_sha2
    assert manifest.files[0].record_count == 2
    assert manifest.files[1].record_count == 1


def test_consolidate_allows_identical_repeated_records_across_files(tmp_path):
    file1 = _write_csv(
        tmp_path / "part1.csv",
        [
            ("24/09/2025", "14,90", "1,00055131"),
            ("25/09/2025", "14,90", "1,00055131"),
        ],
    )
    file2 = _write_csv(
        tmp_path / "part2.csv",
        [
            # Overlapping day, identical values: allowed as duplicate.
            ("25/09/2025", "14,90", "1,00055131"),
            ("26/09/2025", "14,91", "1,00055211"),
        ],
    )

    records, manifest = consolidate_b3_history([file1, file2])

    assert manifest.total_records == 3
    assert manifest.duplicate_count == 1
    assert manifest.conflicts == ()


def test_consolidate_rejects_same_date_conflicts_and_attaches_manifest(tmp_path):
    file1 = _write_csv(
        tmp_path / "part1.csv",
        [("24/09/2025", "14,90", "1,00055131")],
    )
    file2 = _write_csv(
        tmp_path / "part2.csv",
        # Same date, different reported values: conflict.
        [("24/09/2025", "14,91", "1,00055211")],
    )

    with pytest.raises(B3HistoryConflictError) as excinfo:
        consolidate_b3_history([file1, file2])

    manifest = excinfo.value.manifest
    assert manifest.conflict_count == 1
    assert "24/09/2025" not in manifest.conflicts[0]
    assert "2025-09-24" in manifest.conflicts[0]


def test_consolidate_reports_gaps_without_filling_them(tmp_path):
    # Both dates are business days (Wed/Fri), with a missing Thursday.
    file1 = _write_csv(
        tmp_path / "gap.csv",
        [
            ("24/09/2025", "14,90", "1,00055131"),
            ("26/09/2025", "14,91", "1,00055211"),
        ],
    )

    records, manifest = consolidate_b3_history([file1])

    assert manifest.gap_count == 1
    assert manifest.gaps == (date(2025, 9, 25),)
    # The gap is reported, never synthesized into the consolidated series.
    assert [record.reference_date for record in records] == [
        date(2025, 9, 24),
        date(2025, 9, 26),
    ]


def test_consolidate_reports_divergence_without_rejecting(tmp_path):
    file1 = _write_csv(
        tmp_path / "divergent.csv",
        # Fator diário does not match the recalculation from Média.
        [("24/09/2025", "14,90", "0,00000000")],
    )

    records, manifest = consolidate_b3_history([file1])

    assert manifest.divergence_count == 1
    assert "2025-09-24" in manifest.divergences[0]
    assert len(records) == 1


def test_consolidate_counts_divergence_once_per_canonical_date(tmp_path):
    file1 = _write_csv(
        tmp_path / "part1.csv",
        # Fator diário does not match the recalculation from Média.
        [("24/09/2025", "14,90", "0,00000000")],
    )
    file2 = _write_csv(
        tmp_path / "part2.csv",
        # Same date, identical (divergent) record: allowed as duplicate.
        [("24/09/2025", "14,90", "0,00000000")],
    )

    records, manifest = consolidate_b3_history([file1, file2])

    assert manifest.duplicate_count == 1
    assert manifest.conflicts == ()
    # The identical divergent record appears in two files, but must be
    # counted/listed only once, keyed by canonical consolidated date.
    assert manifest.divergence_count == 1
    assert len(records) == 1


def test_consolidate_rejects_empty_path_list():
    with pytest.raises(B3HistoryFormatError):
        consolidate_b3_history([])


def test_calculate_b3_accumulated_from_history_matches_direct_call(tmp_path):
    file1 = _write_csv(
        tmp_path / "part1.csv",
        [
            ("24/09/2025", "14,90", "1,00055131"),
            ("25/09/2025", "14,91", "1,00055211"),
        ],
    )
    records, _manifest = consolidate_b3_history([file1])

    start = date(2025, 9, 24)
    end = date(2025, 9, 26)
    percentual = Decimal("114.0000")

    from_history = calculate_b3_accumulated_from_history(
        records, start, end, percentual, data_version="test-history"
    )
    direct = calculate_b3_accumulated(
        to_b3_rate_observations(records),
        start,
        end,
        percentual,
        data_version="test-history",
    )

    assert from_history == direct
    assert from_history.observations == 2


LOCAL_B3_CSV = Path(__file__).parents[1] / "local-data" / "DI over-24-09-2025.csv"


@pytest.mark.skipif(
    not LOCAL_B3_CSV.exists(),
    reason="fixture anual B3 local não publicado neste repositório",
)
def test_consolidate_official_local_annual_fixture():
    records, manifest = consolidate_b3_history([LOCAL_B3_CSV])

    assert manifest.total_records == 251
    assert manifest.period_start == date(2025, 9, 24)
    assert manifest.period_end == date(2026, 9, 23)
    assert manifest.duplicate_count == 0
    assert manifest.conflicts == ()
    assert manifest.divergence_count == 0
    assert len(manifest.files) == 1
    assert manifest.files[0].sha256 == hashlib.sha256(
        LOCAL_B3_CSV.read_bytes()
    ).hexdigest()

    for percentual, expected in (
        (Decimal("100.0000"), Decimal("1.14498907")),
        (Decimal("114.0000"), Decimal("1.16689290")),
    ):
        result = calculate_b3_accumulated_from_history(
            records,
            date(2025, 9, 24),
            date(2026, 9, 24),
            percentual,
            data_version="local-b3-history-fixture",
        )
        assert result.observations == 251
        assert result.final_factor_round8 == expected
