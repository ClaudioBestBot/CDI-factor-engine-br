"""Política decimal determinística do motor.

Centraliza a base de cálculo (252 dias úteis), a precisão interna usada
para a potenciação fracionária e a regra de truncagem operacional. Nunca
usar ``float`` binário para valores financeiros: toda a aritmética deste
módulo é feita com :class:`decimal.Decimal`.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, localcontext

# Base de dias úteis anual usada para converter a taxa anual em taxa diária.
ANNUALIZATION_BASE = 252

# Precisão (em dígitos significativos) usada internamente para a
# potenciação fracionária, garantindo margem sobre a truncagem operacional
# de 6 casas decimais. Não é aplicada como arredondamento intermediário.
INTERNAL_PRECISION = 60

# Número de casas decimais truncadas (não arredondadas) no fator
# operacional final, conforme especificado na fórmula candidata.
OPERATIONAL_TRUNCATION_PLACES = 6


def annual_to_daily_factor(annual_rate: Decimal) -> Decimal:
    """Converte uma taxa anual (base 252, forma decimal) no fator diário.

    ``f_di(d) = (1 + r_d) ** (1 / 252)``

    A potenciação fracionária é calculada em um contexto decimal de alta
    precisão local, sem arredondar o resultado. O expoente ``1/252`` é
    recalculado dentro deste contexto de alta precisão a cada chamada,
    para não herdar a precisão padrão (28 dígitos) do contexto ambiente.
    """

    with localcontext() as ctx:
        ctx.prec = INTERNAL_PRECISION
        daily_exponent = Decimal(1) / Decimal(ANNUALIZATION_BASE)
        base = Decimal(1) + annual_rate
        return base ** daily_exponent


def truncate(value: Decimal, places: int = OPERATIONAL_TRUNCATION_PLACES) -> Decimal:
    """Trunca (nunca arredonda) ``value`` para o número de casas indicado."""

    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_DOWN)
