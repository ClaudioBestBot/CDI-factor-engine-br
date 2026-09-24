# CDI-factor-engine-br

Open, auditable and deterministic engine for Brazilian CDI factor calculations.

## ⚠️ Caráter educacional/técnico — sem afiliação oficial

Este projeto é **material educacional/técnico independente**. Ele **não tem
qualquer afiliação, endosso ou vínculo oficial com a B3 ou com a CETIP**, e
não reproduz nenhuma metodologia oficial publicada por essas instituições.

A metodologia de cálculo implementada é identificada explicitamente como:

```
legacy-reconstructed/max-precision-v1
```

Ou seja: uma reconstrução própria, feita a partir de convenções de mercado
usuais e de evidência legada (planilha), **até que seja confirmada por
documentação oficial e golden cases independentes**. Todo resultado do
motor traz o campo `methodology_version` para deixar essa origem explícita
e rastreável.

## Escopo do MVP 1

Este MVP implementa apenas o **núcleo de cálculo** (domínio, política
decimal, calendário, metodologia, fator diário, acumulador e FatorJ),
independente de interface, banco de dados e do Finance Genie. Estão fora
do escopo desta etapa: coleta automática de dados, curva DI futura,
inflação e impostos, títulos prefixados, carteiras/perfis/recomendações,
API HTTP, integração Flutter e o modo CETIP de precisão reduzida.

## Convenção temporal

- A data inicial (`D0`) tem fator 1 e não é remunerada.
- As observações são acumuladas no intervalo `(start_date, effective_end_date]`.
- Se a taxa da data final solicitada estiver publicada, ela é incluída;
  caso contrário, o motor recua para a última taxa publicada anterior ou
  igual à data solicitada.
- O resultado sempre traz `requested_end_date` e `effective_end_date`.
- Finais de semana e feriados nacionais não geram fatores.
- Séries com lacunas internas, datas duplicadas ou fora de ordem produzem
  erro explícito — nada é preenchido silenciosamente. A série deve chegar
  ao caso de uso estritamente ordenada por data crescente e sem
  duplicatas; ela **não é reordenada nem deduplicada silenciosamente**.

## Calendário aproximado (não oficial)

O calendário de dias úteis usado para identificar finais de semana,
feriados e lacunas internas é uma **aproximação prática**, não uma
reprodução do calendário oficial de negociação da B3: cobre apenas
feriados nacionais fixos e móveis de base cristã (Carnaval, Sexta-feira
Santa e Corpus Christi), sem feriados estaduais, municipais ou pontos
facultativos. Esse calendário é identificado explicitamente pelo campo
`calendar_version` (`approximate-national-holidays-v1`), devolvido em
todo resultado, para deixar essa aproximação rastreável e auditável.

## Fórmula

Para a taxa anual `r_d` (base 252, forma decimal) publicada em uma data,
percentual contratado `p` (forma decimal) e sem arredondamento
intermediário diário (modo `MAX_PRECISION`):

```
f_di(d) = (1 + r_d) ** (1 / 252)
f_contract(d) = 1 + p * (f_di(d) - 1)
factor_j_raw = product(f_contract(d))
factor_j_operational = trunc(factor_j_raw, 6)
```

A truncagem (nunca arredondamento) em seis casas decimais ocorre apenas
no resultado operacional final.

## Uso

```python
from datetime import date
from decimal import Decimal

from cdi_factor_engine import RateObservation, calculate_factor_j

# A série de taxas é fornecida pelo chamador (sem coleta automática nesta
# etapa): uma taxa anual (base 252, forma decimal) por data de referência.
rate_series = [
    RateObservation(date(2018, 11, 23), Decimal("0.064")),
    # ... demais observações do período ...
]

result = calculate_factor_j(
    rate_series=rate_series,
    requested_start_date=date(2018, 11, 23),
    requested_end_date=date(2019, 11, 19),
    percentual=Decimal("1.14"),  # 114% do CDI
)

print(result.to_json_dict())
```

O resultado mínimo inclui `requested_start_date`, `requested_end_date`,
`effective_end_date`, `observations`, `raw_factor`,
`operational_factor_trunc6`, `cutoff_reason`, `precision_mode`,
`methodology_version`, `data_version` e `calendar_version`. Todos os
valores decimais são serializados como texto (nunca `float`).

## Testes

```
pip install -e . pytest
pytest
```

Os testes cobrem, entre outros casos, o fixture sintético de compatibilidade
agregada para o período 2018-11-23 a 2019-11-19 a 114% do CDI (fator bruto
`1.072376520455055...`, fator operacional `1.072376`), reproduzido a partir
de uma série sintética com taxa anual constante de 6,4% a.a. e do calendário
de dias úteis do motor. Este fixture reproduz os **valores agregados**
(observações, fator bruto, fator operacional e valor final) informados na
issue original a partir de uma planilha legada — mas, como não dispomos da
série diária de taxas real dessa planilha, ele **não é uma reprodução
histórica fiel da série de taxas efetivamente publicada** no período, e sim
uma evidência de compatibilidade agregada, consistente com a metodologia
`legacy-reconstructed/max-precision-v1` e não uma prova oficial isolada.

**Limitação conhecida do fixture agregado e teste complementar:** por usar
taxa anual constante em todos os dias, esse fixture sozinho não comprova que
a acumulação multiplica corretamente fatores diários *diferentes* entre si
(o cenário real do CDI, cuja taxa muda ao longo do tempo). Para cobrir essa
lacuna, há um teste adicional (`test_accumulation_with_variable_daily_rates`)
com uma série **sintética e fabricada para fins de teste** — não é a série
real da planilha legada nem dados oficiais de nenhuma fonte — com taxas
anuais que variam a cada dia útil. O valor esperado é calculado por uma
segunda implementação independente da fórmula, escrita diretamente no
teste, o que ajuda a detectar regressões na acumulação com taxas variáveis.
