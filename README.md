# CDI-factor-engine-br

Open, auditable and deterministic engine for Brazilian CDI factor calculations.

## ⚠️ Caráter educacional/técnico — sem afiliação oficial

Este projeto é **material educacional/técnico independente**. Ele **não tem
afiliação, certificação, endosso ou vínculo oficial com a B3 ou com a CETIP**.
O modo B3 é uma implementação independente baseada em documentação pública,
sem alegar reprodução certificada ou oficial de qualquer metodologia.

A metodologia legada de cálculo é identificada explicitamente como:

```
legacy-reconstructed/max-precision-v1
```

Ou seja: uma reconstrução própria, feita a partir de convenções de mercado
usuais e de evidência legada (planilha), **até que seja confirmada por
documentação oficial e golden cases independentes**. Todo resultado do
motor traz o campo `methodology_version` para deixar essa origem explícita
e rastreável.

## Metodologia acumulada DI-B3

Além do modo legado, o motor disponibiliza explicitamente
`b3-accumulated/252-v1`, uma implementação independente do cálculo
acumulado DI-B3. Ela não substitui nem altera
`legacy-reconstructed/max-precision-v1`.

É uma implementação independente baseada na documentação pública da B3,
sem afiliação, certificação ou endosso da B3.

Este modo recebe taxas DI-B3 Over anuais em **percentual** (por exemplo,
`Decimal("14.90")`) e acumula `[start_date, end_date)`: inclui a data
inicial e exclui a final, sem recuo implícito de datas. Ou seja, dado um
intervalo `[start_date, end_date)`, uma observação datada exatamente em
`end_date` **não** é remunerada — apenas observações com
`start_date <= reference_date < end_date` entram no produtório. Para
incluir a última data desejada, informe `end_date` como o dia útil
seguinte a ela. Para cada observação, calcula TDIk em base 252 e
arredonda em 8 casas (half-up), trunca o fator diário e o acumulado em 16
casas após cada multiplicação e arredonda o fator final em 8 casas
(half-up). O percentual contratado deve ter, no máximo, quatro casas
decimais.

**Validação da taxa anual:** `annual_rate_percent` é sempre a taxa DI-B3
Over anual em **forma percentual** (por exemplo, `14.90` para 14,90%
a.a.), nunca em forma decimal (`0.1490`) nem `float`. O importador de CSV
e o consolidador histórico (abaixo) conferem essa taxa contra o "Fator
diário" publicado, recalculando-o pela mesma fórmula de TDIk; qualquer
"Fator diário" que não confira com a "Média" publicada é tratado como
divergência (rejeitada de imediato pelo importador simples
`import_b3_di_csv`, e reportada no manifesto — sem interromper a
consolidação — pelo consolidador histórico de múltiplos arquivos).

```python
from cdi_factor_engine import B3RateObservation, calculate_b3_accumulated

result = calculate_b3_accumulated(
    [B3RateObservation(date(2025, 9, 24), Decimal("14.90"))],
    date(2025, 9, 24),
    date(2025, 9, 25),
    Decimal("114.0000"),
    data_version="local-b3-csv",
)
```

O importador local `import_b3_di_csv(path)` aceita o CSV público B3 com BOM,
`;`, datas `DD/MM/YYYY` e vírgula decimal. Ele localiza o cabeçalho após o
texto introdutório, rejeita `Nenhum resultado` e confere `Fator diário`
contra a taxa `Média` recalculada. Não há download automático, e séries
anuais B3 não são incluídas neste repositório. A metodologia é baseada na
[documentação pública da B3 sobre cálculo acumulado de DI](https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-de-segmentos-e-setoriais/di/metodologia-de-calcudo-acumulado-de-di/);
este projeto continua sem afiliação, certificação ou endosso da B3.

## Histórico DI-B3 consolidado e auditável

Este módulo (`cdi_factor_engine.b3_history`) é independente de
`import_b3_di_csv` (cujo contrato não é alterado) e permite montar um
histórico DI-B3 canônico a partir de **múltiplos** arquivos CSV locais,
tipicamente exportações anuais sucessivas da B3 com períodos adjacentes ou
parcialmente sobrepostos.

Cada observação vira um `B3HistoricalRecord`, com data (`reference_date`),
taxa anual em percentual (`annual_rate_percent`), o "Fator diário" tal
como publicado (`reported_daily_factor`), a proveniência do registro
(`origin`, por padrão o nome do arquivo CSV) e a versão do esquema do
registro (`version`, atualmente `b3-history-record-v1`).

```python
from cdi_factor_engine import (
    calculate_b3_accumulated_from_history,
    consolidate_b3_history,
)

records, manifest = consolidate_b3_history(
    ["local-data/DI-2024.csv", "local-data/DI-2025.csv"]
)
result = calculate_b3_accumulated_from_history(
    records,
    date(2024, 1, 2),
    date(2025, 1, 2),
    Decimal("114.0000"),
    data_version="local-b3-history",
)
```

Regras de consolidação:

- **Cronologia estrita por arquivo:** cada arquivo é lido isoladamente e
  deve chegar estritamente ordenado por data crescente; um arquivo fora de
  ordem, ou com data repetida dentro dele mesmo, **não é reordenado nem
  deduplicado silenciosamente** — gera `B3HistoryUnsortedError`.
- **Repetição idêntica é permitida:** se o mesmo dia aparecer em mais de
  um arquivo (por exemplo, períodos que se sobrepõem em um dia), isso só é
  aceito quando o registro for **idêntico** (mesma `Média` e mesmo `Fator
  diário`); é contado como duplicata no manifesto.
- **Conflito de mesma data é rejeitado:** o mesmo dia com valores
  diferentes entre arquivos é um conflito. Todos os arquivos informados
  são lidos e mesclados integralmente antes de qualquer decisão; somente
  depois, se houver um ou mais conflitos, a consolidação é interrompida
  com `B3HistoryConflictError`. O manifesto disponível em `error.manifest`
  é o manifesto **completo** (construído a partir de todos os arquivos
  informados, não um recorte parcial até o primeiro conflito encontrado)
  — mas nenhuma série "corrigida" ou parcial é devolvida como resultado
  válido da função.
- **Lacunas nunca são preenchidas:** dias úteis (conforme o calendário
  aproximado do motor) sem nenhum registro no intervalo coberto pela
  série consolidada são apenas listados em `manifest.gaps` — nunca
  interpolados, nem inferidos a partir de dias vizinhos.
- **Divergências são reportadas, não corrigidas:** um registro cujo
  `Fator diário` informado não confere com o valor recalculado a partir
  da `Média` (mesma fórmula de TDIk usada em `import_b3_di_csv`) é listado
  em `manifest.divergences`. Ao contrário de um conflito entre fontes,
  isso não interrompe a consolidação — é um sinal de qualidade a ser
  auditado pelo chamador, não uma contradição irreconciliável. Cada
  divergência é contada **uma única vez por data canônica** consolidada:
  se o mesmo registro divergente se repetir, idêntico, em mais de um
  arquivo (uma duplicata permitida), ele não é listado nem contado mais
  de uma vez em `manifest.divergences`.

O manifesto (`B3HistoryManifest`) é auditável e serializável via
`to_json_dict()`, trazendo `period_start`/`period_end`, `total_records`,
`duplicate_count`, `gap_count`/`gaps`, `conflict_count`/`conflicts`,
`divergence_count`/`divergences` e, para cada arquivo consolidado, seu
caminho, o SHA-256 do conteúdo bruto e a contagem de registros — o
suficiente para provar, a posteriori, exatamente quais arquivos e bytes
produziram a série usada em um cálculo.

A série consolidada devolvida por `consolidate_b3_history` pode alimentar
diretamente `calculate_b3_accumulated_from_history` (um atalho fino sobre
`calculate_b3_accumulated`, sem alterar a metodologia
`b3-accumulated/252-v1`) ou ser convertida para `B3RateObservation` via
`to_b3_rate_observations` para uso manual.

## Escopo do MVP 1

Este MVP implementa apenas o **núcleo de cálculo** (domínio, política
decimal, calendário, metodologia, fator diário, acumulador e FatorJ),
independente de interface, banco de dados e do Finance Genie. Estão fora
do escopo desta etapa: coleta automática de dados, curva DI futura,
inflação e impostos, títulos prefixados, carteiras/perfis/recomendações,
API HTTP, integração Flutter e o modo CETIP de precisão reduzida.

## Escopo do MVP 3

Este MVP acrescenta apenas o histórico DI-B3 consolidado e auditável
(`cdi_factor_engine.b3_history`): registro canônico, importação de
múltiplos CSVs locais, consolidação cronológica e manifesto de
auditoria. Não altera nenhuma metodologia, fórmula, arredondamento ou
contrato público existente (`legacy-reconstructed/max-precision-v1` e
`b3-accumulated/252-v1` permanecem inalterados) e continua fora de
escopo: coleta automática de dados, API HTTP, banco de dados e qualquer
integração externa.

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

Os testes de `tests/test_b3_history.py` cobrem, com CSVs sintéticos
fabricados em `tmp_path` (não dados oficiais), a consolidação cronológica
de múltiplos arquivos, a repetição idêntica permitida, o conflito de
mesma data rejeitado (com o manifesto anexado ao erro), a lacuna
reportada sem preenchimento, a divergência de `Fator diário` reportada
sem interromper a consolidação, o SHA-256 por arquivo no manifesto e a
rejeição de entradas fora de ordem sem reordenação silenciosa. Há também
um teste opcional (`test_consolidate_official_local_annual_fixture`),
pulado automaticamente quando o arquivo não está presente, que exercita o
mesmo pipeline sobre `local-data/DI over-24-09-2025.csv` — um CSV oficial
B3 mantido **apenas localmente** (listado em `.gitignore`, nunca versionado
neste repositório) — reproduzindo os mesmos fatores finais já validados
pelo teste equivalente de `import_b3_di_csv`.
