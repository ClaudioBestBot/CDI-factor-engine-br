"""Conversão da taxa anual publicada para o fator diário e o fator contratado.

``f_di(d) = (1 + r_d) ** (1 / 252)``
``f_contract(d) = 1 + p * (f_di(d) - 1)``

Nenhum arredondamento intermediário é aplicado nestas funções (modo de
precisão máxima).
"""

from __future__ import annotations

from decimal import Decimal

from .decimal_policy import annual_to_daily_factor


def compute_daily_di_factor(annual_rate: Decimal) -> Decimal:
    """Fator diário do DI a partir da taxa anual publicada (base 252)."""

    return annual_to_daily_factor(annual_rate)


def compute_contract_factor(daily_di_factor: Decimal, percentual: Decimal) -> Decimal:
    """Fator diário do contrato para um percentual ``p`` do CDI (decimal)."""

    return Decimal(1) + percentual * (daily_di_factor - Decimal(1))
