"""Interpolação e extrapolação Flat Forward em base 252, somente Decimal."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Sequence

INTERNAL_PRECISION = 60


def _validate_vertices(du_previous: int, du_next: int, rate_previous: Decimal, rate_next: Decimal) -> None:
    if du_previous >= du_next:
        raise ValueError("DU vertices must be strictly increasing")
    if rate_previous <= Decimal("-100") or rate_next <= Decimal("-100"):
        raise ValueError("annual rates must be greater than -100 percent")


def _factor(rate_percent: Decimal) -> Decimal:
    return Decimal(1) + rate_percent / Decimal(100)


def _rate(factor: Decimal) -> Decimal:
    return (factor - Decimal(1)) * Decimal(100)


def flat_forward_interpolate(
    du_previous: int,
    rate_previous: Decimal,
    du_next: int,
    rate_next: Decimal,
    du_target: int,
) -> Decimal:
    """Retorna a taxa anual percentual no intervalo, sem extrapolação."""

    _validate_vertices(du_previous, du_next, rate_previous, rate_next)
    if not du_previous <= du_target <= du_next:
        raise ValueError("DU_target must be between the vertices")
    if du_target == du_previous:
        return rate_previous
    if du_target == du_next:
        return rate_next
    with localcontext() as ctx:
        ctx.prec = INTERNAL_PRECISION
        weight = Decimal(du_target - du_previous) / Decimal(du_next - du_previous)
        ratio = _factor(rate_next) / _factor(rate_previous)
        factor = _factor(rate_previous) * (ratio.ln() * weight).exp()
        return _rate(factor)


def flat_forward_extrapolate(
    du_previous: int,
    rate_previous: Decimal,
    du_last: int,
    rate_last: Decimal,
    du_target: int,
) -> Decimal:
    """Projeta após o último vértice usando o forward implícito final."""

    _validate_vertices(du_previous, du_last, rate_previous, rate_last)
    if du_target <= du_last:
        raise ValueError("DU_target must be after the last vertex")
    with localcontext() as ctx:
        ctx.prec = INTERNAL_PRECISION
        weight = Decimal(du_target - du_previous) / Decimal(du_last - du_previous)
        ratio = _factor(rate_last) / _factor(rate_previous)
        factor = _factor(rate_previous) * (ratio.ln() * weight).exp()
        return _rate(factor)


def flat_forward_extrapolate_curve(
    vertices: Sequence[tuple[int, Decimal]], du_target: int
) -> Decimal:
    """Extrapola uma curva usando os dois últimos vértices."""

    if len(vertices) < 2:
        raise ValueError("at least two curve vertices are required")
    du_previous, rate_previous = vertices[-2]
    du_last, rate_last = vertices[-1]
    return flat_forward_extrapolate(
        du_previous, rate_previous, du_last, rate_last, du_target
    )


def rounded_rate_percent(rate: Decimal) -> Decimal:
    """Camada de apresentação: arredonda a taxa final a três casas."""

    return rate.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
