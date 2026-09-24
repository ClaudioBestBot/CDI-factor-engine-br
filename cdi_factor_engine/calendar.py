"""Convenção temporal e calendário de dias úteis.

Implementa a convenção D0 (data inicial com fator 1, sem remuneração da
própria data) e um calendário de feriados nacionais brasileiros usado
apenas para identificar dias úteis e validar lacunas internas na série de
taxas informada pelo chamador.

Este calendário cobre os feriados nacionais fixos e móveis de base
cristã (Carnaval, Sexta-feira Santa e Corpus Christi, calculados a partir
da Páscoa). Feriados estaduais, municipais e pontos facultativos não são
considerados. Isto é uma aproximação prática para validação de lacunas,
não uma reprodução do calendário oficial de negociação da B3.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def _easter_sunday(year: int) -> date:
    """Calcula a data da Páscoa (algoritmo gregoriano anônimo)."""

    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=None)
def national_holidays(year: int) -> frozenset[date]:
    """Feriados nacionais brasileiros (fixos e móveis) de um ano civil."""

    easter = _easter_sunday(year)
    return frozenset(
        {
            date(year, 1, 1),  # Confraternização Universal
            date(year, 4, 21),  # Tiradentes
            date(year, 5, 1),  # Dia do Trabalho
            date(year, 9, 7),  # Independência do Brasil
            date(year, 10, 12),  # Nossa Senhora Aparecida
            date(year, 11, 2),  # Finados
            date(year, 11, 15),  # Proclamação da República
            date(year, 12, 25),  # Natal
            easter - timedelta(days=48),  # Segunda-feira de Carnaval
            easter - timedelta(days=47),  # Terça-feira de Carnaval
            easter - timedelta(days=2),  # Sexta-feira Santa
            easter + timedelta(days=60),  # Corpus Christi
        }
    )


def is_weekend(reference_date: date) -> bool:
    return reference_date.weekday() >= 5


def is_national_holiday(reference_date: date) -> bool:
    return reference_date in national_holidays(reference_date.year)


def is_business_day(reference_date: date) -> bool:
    """Finais de semana e feriados nacionais não são dias úteis."""

    return not is_weekend(reference_date) and not is_national_holiday(reference_date)


def business_days_between(start_exclusive: date, end_inclusive: date) -> list[date]:
    """Lista os dias úteis no intervalo ``(start_exclusive, end_inclusive]``."""

    if end_inclusive < start_exclusive:
        return []
    days = []
    current = start_exclusive + timedelta(days=1)
    while current <= end_inclusive:
        if is_business_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days
