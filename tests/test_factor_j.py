"""Testes obrigatórios do núcleo CDI/FatorJ (issue #1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext

import pytest

from cdi_factor_engine import RateObservation, calculate_factor_j
from cdi_factor_engine.accumulator import (
    CUTOFF_FALLBACK_TO_LAST_PUBLISHED_RATE,
    CUTOFF_REQUESTED_END_DATE_PUBLISHED,
    CUTOFF_START_EQUALS_END,
)
from cdi_factor_engine.calendar import business_days_between
from cdi_factor_engine.methodology import METHODOLOGY_VERSION, PRECISION_MODE_MAX
from cdi_factor_engine.validation import (
    DuplicateDateError,
    InternalGapError,
    UnsortedSeriesError,
)


def flat_rate_series(
    start: date, end: date, annual_rate: Decimal, *, include_start: bool = True
) -> list[RateObservation]:
    """Série sintética com a mesma taxa anual em todo dia útil do intervalo."""

    observations = []
    if include_start:
        observations.append(RateObservation(start, annual_rate))
    for business_day in business_days_between(start, end):
        observations.append(RateObservation(business_day, annual_rate))
    return observations


# 1. start == end retorna 1.
def test_start_equals_end_returns_one():
    start = date(2019, 3, 12)
    series = flat_rate_series(start, start, Decimal("0.064"))
    result = calculate_factor_j(series, start, start, Decimal("1.14"))
    assert result.observations == 0
    assert result.raw_factor == Decimal(1)
    assert result.operational_factor_trunc6 == Decimal("1.000000")
    assert result.cutoff_reason == CUTOFF_START_EQUALS_END
    assert result.effective_end_date == start


# 2. A taxa da data inicial é excluída.
def test_start_date_rate_is_excluded():
    start = date(2019, 3, 12)  # terça-feira
    end = date(2019, 3, 13)  # quarta-feira
    series = [
        RateObservation(start, Decimal("0.50")),  # taxa absurda, não deve contar
        RateObservation(end, Decimal("0.064")),
    ]
    result = calculate_factor_j(series, start, end, Decimal("1.14"))
    assert result.observations == 1
    with localcontext() as ctx:
        ctx.prec = 60
        only_from_end_rate = Decimal(1) + Decimal("1.14") * (
            (Decimal(1) + Decimal("0.064")) ** (Decimal(1) / Decimal(252)) - 1
        )
    assert abs(result.raw_factor - only_from_end_rate) < Decimal("1E-55")


# 3. Data final publicada é incluída.
def test_requested_end_date_published_is_included():
    start = date(2019, 3, 12)
    end = date(2019, 3, 13)
    series = [
        RateObservation(start, Decimal("0.064")),
        RateObservation(end, Decimal("0.064")),
    ]
    result = calculate_factor_j(series, start, end, Decimal("1.0"))
    assert result.effective_end_date == end
    assert result.observations == 1
    assert result.cutoff_reason == CUTOFF_REQUESTED_END_DATE_PUBLISHED


# 4. Data final sem taxa recua para a última taxa publicada.
def test_missing_requested_end_date_falls_back_to_last_published():
    start = date(2019, 3, 11)  # segunda-feira
    last_published = date(2019, 3, 13)  # quarta-feira (última taxa disponível)
    requested_end = date(2019, 3, 15)  # sexta-feira, sem taxa publicada
    series = [
        RateObservation(start, Decimal("0.064")),
        RateObservation(date(2019, 3, 12), Decimal("0.064")),
        RateObservation(last_published, Decimal("0.064")),
    ]
    result = calculate_factor_j(series, start, requested_end, Decimal("1.0"))
    assert result.requested_end_date == requested_end
    assert result.effective_end_date == last_published
    assert result.cutoff_reason == CUTOFF_FALLBACK_TO_LAST_PUBLISHED_RATE
    assert result.observations == 2


# 5. Fim de semana não adiciona fatores.
def test_weekend_does_not_add_factors():
    start = date(2019, 3, 15)  # sexta-feira
    end = date(2019, 3, 18)  # segunda-feira
    saturday = date(2019, 3, 16)
    sunday = date(2019, 3, 17)
    series = [
        RateObservation(start, Decimal("0.064")),
        RateObservation(saturday, Decimal("0.064")),  # não deve gerar fator
        RateObservation(sunday, Decimal("0.064")),  # não deve gerar fator
        RateObservation(end, Decimal("0.064")),
    ]
    result = calculate_factor_j(series, start, end, Decimal("1.14"))
    assert result.observations == 1
    with localcontext() as ctx:
        ctx.prec = 60
        only_monday_factor = Decimal(1) + Decimal("1.14") * (
            (Decimal(1) + Decimal("0.064")) ** (Decimal(1) / Decimal(252)) - 1
        )
    assert abs(result.raw_factor - only_monday_factor) < Decimal("1E-55")


# 6. p = 0 retorna 1.
def test_zero_percentual_returns_one():
    start = date(2019, 3, 11)
    end = date(2019, 3, 15)
    series = flat_rate_series(start, end, Decimal("0.064"))
    result = calculate_factor_j(series, start, end, Decimal("0"))
    assert result.raw_factor == Decimal(1)
    assert result.operational_factor_trunc6 == Decimal("1.000000")


# 7. p = 100% reproduz a curva CDI.
def test_hundred_percent_reproduces_cdi_curve():
    start = date(2019, 3, 11)
    end = date(2019, 3, 15)
    annual_rate = Decimal("0.064")
    series = flat_rate_series(start, end, annual_rate)
    result = calculate_factor_j(series, start, end, Decimal("1"))
    with localcontext() as ctx:
        ctx.prec = 60
        daily_di_factor = (Decimal(1) + annual_rate) ** (Decimal(1) / Decimal(252))
        expected = daily_di_factor**result.observations
    assert abs(result.raw_factor - expected) < Decimal("1E-55")


# 8. Um dia a 6,4% a.a. e 114%: bruto 1.000280670837514...; truncado 1.000280.
def test_single_day_six_point_four_percent_at_114_percent():
    start = date(2018, 11, 23)
    end = date(2018, 11, 26)  # próximo dia útil (segunda-feira)
    series = [
        RateObservation(start, Decimal("0.064")),
        RateObservation(end, Decimal("0.064")),
    ]
    result = calculate_factor_j(series, start, end, Decimal("1.14"))
    assert result.observations == 1
    # A issue apresenta o valor truncado em "1.000280670837514...";
    # validamos os dígitos exatamente informados.
    assert str(result.raw_factor).startswith("1.000280670837514")
    assert result.operational_factor_trunc6 == Decimal("1.000280")


# 9. Golden test histórico de 2018-2019.
def test_golden_case_2018_2019():
    start = date(2018, 11, 23)
    end = date(2019, 11, 19)
    series = flat_rate_series(start, end, Decimal("0.064"))
    result = calculate_factor_j(
        series,
        start,
        end,
        Decimal("1.14"),
        data_version="golden-fixture-legacy-spreadsheet-v1",
    )
    assert result.observations == 249
    assert result.effective_end_date == end
    assert result.cutoff_reason == CUTOFF_REQUESTED_END_DATE_PUBLISHED
    # A issue apresenta o fator bruto esperado como "1.072376520455055...";
    # validamos os dígitos exatamente informados.
    assert str(result.raw_factor).startswith("1.072376520455055")
    assert result.operational_factor_trunc6 == Decimal("1.072376")

    principal = Decimal("120000.00")
    final_value = (principal * result.operational_factor_trunc6).quantize(Decimal("0.01"))
    assert final_value == Decimal("128685.12")

    assert result.methodology_version == METHODOLOGY_VERSION
    assert result.precision_mode == PRECISION_MODE_MAX


# 10. Dados duplicados, desordenados ou com lacuna interna falham explicitamente.
def test_duplicate_dates_fail_explicitly():
    start = date(2019, 3, 11)
    end = date(2019, 3, 13)
    series = [
        RateObservation(start, Decimal("0.064")),
        RateObservation(date(2019, 3, 12), Decimal("0.064")),
        RateObservation(date(2019, 3, 12), Decimal("0.064")),  # duplicada
        RateObservation(end, Decimal("0.064")),
    ]
    with pytest.raises(DuplicateDateError):
        calculate_factor_j(series, start, end, Decimal("1.0"))


def test_unsorted_series_fails_explicitly():
    start = date(2019, 3, 11)
    end = date(2019, 3, 13)
    series = [
        RateObservation(date(2019, 3, 12), Decimal("0.064")),
        RateObservation(start, Decimal("0.064")),  # fora de ordem
        RateObservation(end, Decimal("0.064")),
    ]
    with pytest.raises(UnsortedSeriesError):
        calculate_factor_j(series, start, end, Decimal("1.0"))


def test_internal_gap_fails_explicitly():
    start = date(2019, 3, 11)  # segunda-feira
    end = date(2019, 3, 14)  # quinta-feira
    series = [
        RateObservation(start, Decimal("0.064")),
        # falta 2019-03-12 (terça-feira, dia útil) -- lacuna interna
        RateObservation(date(2019, 3, 13), Decimal("0.064")),
        RateObservation(end, Decimal("0.064")),
    ]
    with pytest.raises(InternalGapError):
        calculate_factor_j(series, start, end, Decimal("1.0"))


# 11. Datas não possuem horário/timezone.
def test_dates_have_no_time_or_timezone():
    start = date(2019, 3, 11)
    end = date(2019, 3, 13)
    series = flat_rate_series(start, end, Decimal("0.064"))
    result = calculate_factor_j(series, start, end, Decimal("1.0"))
    for value in (
        result.requested_start_date,
        result.requested_end_date,
        result.effective_end_date,
    ):
        assert type(value) is date
    payload = result.to_json_dict()
    assert payload["requested_start_date"] == "2019-03-11"
    assert "T" not in payload["requested_start_date"]


# 12. Para 100%, sem truncagem intermediária: F(a,c) = F(a,b) * F(b,c).
def test_factor_is_multiplicative_without_intermediate_truncation():
    a = date(2019, 3, 8)  # sexta-feira
    b = date(2019, 3, 13)  # quarta-feira
    c = date(2019, 3, 20)  # quarta-feira seguinte
    series = flat_rate_series(a, c, Decimal("0.064"))

    result_ac = calculate_factor_j(series, a, c, Decimal("1.0"))
    result_ab = calculate_factor_j(series, a, b, Decimal("1.0"))
    result_bc = calculate_factor_j(series, b, c, Decimal("1.0"))

    with localcontext() as ctx:
        ctx.prec = 60
        product_ab_bc = result_ab.raw_factor * result_bc.raw_factor
    assert result_ac.raw_factor == product_ab_bc
    assert result_ac.observations == result_ab.observations + result_bc.observations


def test_requested_start_after_end_raises():
    from cdi_factor_engine.accumulator import InvalidDateRangeError

    start = date(2019, 3, 15)
    end = date(2019, 3, 11)
    series = flat_rate_series(end, start, Decimal("0.064"))
    with pytest.raises(InvalidDateRangeError):
        calculate_factor_j(series, start, end, Decimal("1.0"))


# 13. Reforço de validação: acumulação com taxas VARIÁVEIS dia a dia.
#
# O golden test (item 9 acima) usa uma série sintética de taxa CONSTANTE
# (6,4% a.a. em todos os dias), o que valida a truncagem/observações/
# effective_end_date, mas não comprova, isoladamente, que a acumulação
# multiplica corretamente fatores diários DIFERENTES entre si (o cenário
# real do CDI, cuja taxa muda ao longo do tempo).
#
# Este teste usa uma série sintética adicional, com taxas anuais que
# variam a cada dia útil dentro do período. É explicitamente uma série
# fabricada para fins de teste (não é a série real da planilha legada
# nem dados oficiais de nenhuma fonte) -- os valores foram escolhidos
# apenas para não serem todos iguais entre si, simulando o padrão de
# "taxa muda a cada poucos dias e depois se mantém" observado na prática,
# sem qualquer pretensão de precisão histórica.
#
# O valor esperado é calculado por uma segunda implementação da fórmula,
# escrita diretamente neste teste (independente do código de produção),
# em um contexto decimal de alta precisão. Isso detecta regressões na
# acumulação (por exemplo, o bug de precisão do expoente 1/252 corrigido
# durante o desenvolvimento deste MVP, que só se manifestava ao comparar
# com uma potenciação calculada fora do contexto de alta precisão).
def test_accumulation_with_variable_daily_rates():
    start = date(2019, 8, 1)  # quinta-feira
    end = date(2019, 8, 15)  # quinta-feira (10 dias úteis após o início)

    business_days = business_days_between(start, end)
    assert len(business_days) == 10  # garante a premissa do teste

    # Série sintética e fabricada: taxa anual (base 252, forma decimal)
    # variando a cada dia útil, sem repetir o mesmo valor em sequência
    # mais de duas vezes, para exercitar de fato fatores diários distintos.
    synthetic_annual_rates = [
        Decimal("0.0640"),
        Decimal("0.0640"),
        Decimal("0.0590"),
        Decimal("0.0590"),
        Decimal("0.0700"),
        Decimal("0.0555"),
        Decimal("0.0620"),
        Decimal("0.0480"),
        Decimal("0.0480"),
        Decimal("0.0665"),
    ]
    assert len(synthetic_annual_rates) == len(business_days)
    # Confirma que a premissa "taxas variáveis" se sustenta: nem todas as
    # observações têm a mesma taxa.
    assert len(set(synthetic_annual_rates)) > 1

    series = [RateObservation(start, Decimal("0.0640"))] + [
        RateObservation(business_day, rate)
        for business_day, rate in zip(business_days, synthetic_annual_rates)
    ]

    percentual = Decimal("1.14")  # 114% do CDI, mesmo percentual do golden test
    result = calculate_factor_j(series, start, end, percentual)

    assert result.observations == 10
    assert result.effective_end_date == end
    assert result.cutoff_reason == CUTOFF_REQUESTED_END_DATE_PUBLISHED

    # Segunda implementação da fórmula, independente da produção,
    # calculada com alta precisão e sem arredondamento intermediário.
    with localcontext() as ctx:
        ctx.prec = 60
        expected_raw_factor = Decimal(1)
        for annual_rate in synthetic_annual_rates:
            daily_di_factor = (Decimal(1) + annual_rate) ** (Decimal(1) / Decimal(252))
            contract_factor = Decimal(1) + percentual * (daily_di_factor - Decimal(1))
            expected_raw_factor *= contract_factor

    assert result.raw_factor == expected_raw_factor

    expected_operational_factor = expected_raw_factor.quantize(
        Decimal("0.000001"), rounding="ROUND_DOWN"
    )
    assert result.operational_factor_trunc6 == expected_operational_factor

    # A truncagem só ocorre no resultado final: o fator bruto acumulado
    # continua com casas decimais além da sexta, mesmo com taxas variáveis.
    assert result.raw_factor != result.operational_factor_trunc6
