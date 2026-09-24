"""Calendário nacional ANBIMA reconstruído e importação auditável de .xls.

Os dados gerados neste módulo são uma reconstrução pública algorítmica dos
feriados nacionais, não uma cópia do calendário oficial da ANBIMA/B3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import csv
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

ANBIMA_CALENDAR_VERSION = "anbima-national-holidays-2001-2099-v2023"


def _easter_sunday(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(year, month, ((h + l - 7 * m + 114) % 31) + 1)


@dataclass(frozen=True)
class AnbimaHoliday:
    reference_date: date
    names: tuple[str, ...]

    @property
    def weekday(self) -> str:
        return self.reference_date.strftime("%A")


@dataclass(frozen=True)
class AnbimaCalendar:
    version: str
    source: str
    sha256: str | None
    period_start: date
    period_end: date
    holidays: tuple[AnbimaHoliday, ...]

    @property
    def dates(self) -> frozenset[date]:
        return frozenset(item.reference_date for item in self.holidays)

    @property
    def period_covered(self) -> tuple[date, date]:
        return self.period_start, self.period_end

    @property
    def records(self) -> tuple[AnbimaHoliday, ...]:
        return self.holidays


def _holiday_names(year: int) -> Mapping[date, tuple[str, ...]]:
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1): ("Confraternização Universal",),
        date(year, 4, 21): ("Tiradentes",),
        date(year, 5, 1): ("Dia Mundial do Trabalho",),
        date(year, 9, 7): ("Independência do Brasil",),
        date(year, 10, 12): ("Nossa Senhora Aparecida",),
        date(year, 11, 2): ("Finados",),
        date(year, 11, 15): ("Proclamação da República",),
        date(year, 12, 25): ("Natal",),
        easter - timedelta(days=47): ("Carnaval",),
        easter - timedelta(days=2): ("Sexta-feira Santa",),
        easter + timedelta(days=60): ("Corpus Christi",),
    }


def generate_anbima_calendar(
    start_year: int = 2001, end_year: int = 2099
) -> AnbimaCalendar:
    if start_year > end_year:
        raise ValueError("start_year must be less than or equal to end_year")
    merged: dict[date, list[str]] = {}
    for year in range(start_year, end_year + 1):
        for holiday_date, names in _holiday_names(year).items():
            merged.setdefault(holiday_date, []).extend(names)
    holidays = tuple(
        AnbimaHoliday(day, tuple(names))
        for day, names in sorted(merged.items())
    )
    return AnbimaCalendar(
        ANBIMA_CALENDAR_VERSION,
        "public-algorithmic-reconstruction",
        None,
        date(start_year, 1, 1),
        date(end_year, 12, 31),
        holidays,
    )


@lru_cache(maxsize=1)
def _default_calendar() -> AnbimaCalendar:
    return generate_anbima_calendar()


def is_anbima_business_day(
    reference_date: date, calendar: AnbimaCalendar | None = None
) -> bool:
    selected = calendar or _default_calendar()
    return reference_date.weekday() < 5 and reference_date not in selected.dates


def _parse_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"invalid holiday date: {value!r}")


def _calendar_from_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    version: str,
    source: str,
    sha256: str | None,
) -> AnbimaCalendar:
    merged: dict[date, list[str]] = {}
    for row in rows:
        holiday_date = _parse_date(row["Data"])
        name = str(row["Feriado"]).strip()
        if not name:
            raise ValueError("Feriado must not be empty")
        merged.setdefault(holiday_date, [])
        if name not in merged[holiday_date]:
            merged[holiday_date].append(name)
    if not merged:
        raise ValueError("holiday file contains no records")
    holidays = tuple(
        AnbimaHoliday(day, tuple(names))
        for day, names in sorted(merged.items())
    )
    return AnbimaCalendar(
        version,
        source,
        sha256,
        holidays[0].reference_date,
        holidays[-1].reference_date,
        holidays,
    )


def import_anbima_holidays_xls(
    path: str | Path,
    *,
    calendar_version: str = ANBIMA_CALENDAR_VERSION,
) -> AnbimaCalendar:
    """Importa .xls com colunas ``Data; Dia da Semana; Feriado``.

    ``xlrd`` é opcional para manter o núcleo somente-stdlib. O hash é dos
    bytes brutos e o período é calculado dos registros, após consolidação.
    """

    file_path = Path(path)
    raw = file_path.read_bytes()
    try:
        import xlrd
    except ImportError as exc:
        raise ImportError(
            "import_anbima_holidays_xls requires the optional 'xlrd' dependency"
        ) from exc
    workbook = xlrd.open_workbook(file_contents=raw)
    sheet = workbook.sheet_by_index(0)
    headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
    required = {"Data", "Dia da Semana", "Feriado"}
    if not required.issubset(headers):
        raise ValueError("holiday .xls must contain Data, Dia da Semana and Feriado")
    indexes = {header: headers.index(header) for header in required}
    rows = []
    for row_index in range(1, sheet.nrows):
        excel_date = sheet.cell_value(row_index, indexes["Data"])
        value = xlrd.xldate_as_datetime(excel_date, workbook.datemode)
        rows.append({"Data": value.date(), "Feriado": sheet.cell_value(row_index, indexes["Feriado"])})
    return _calendar_from_rows(
        rows,
        version=calendar_version,
        source=str(file_path),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def import_anbima_holidays_csv_fixture(
    path: str | Path, *, calendar_version: str = ANBIMA_CALENDAR_VERSION
) -> AnbimaCalendar:
    """Importador stdlib para fixture sintético com o mesmo esquema do .xls."""

    file_path = Path(path)
    raw = file_path.read_bytes()
    with file_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream, delimiter=";")
        return _calendar_from_rows(
            rows,
            version=calendar_version,
            source=str(file_path),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
