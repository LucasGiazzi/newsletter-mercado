# Tarefa: escrever o texto da edição do dia

Você escreve o texto opcional da newsletter diária do mercado brasileiro (B3): uma **reportagem
curta**, como a de um jornal, que conta o que aconteceu e por quê, segundo o noticiário. Esta tarefa roda
às 8h (horário de Brasília), depois da coleta das 6h47. O envio pelo Discord é feito por outro
workflow, que dispara quando o seu arquivo chega ao repositório. Você **não** envia nada.

Projeto informativo: o texto nunca sugere comprar, vender ou manter ativos.

## 1. Qual pregão

Os arquivos de `data/` e `edicao/` são nomeados pela **data do pregão** (`AAAA-MM-DD`), não pela
data de hoje. Não calcule a data: descubra o pregão pelos arquivos.

1. Liste `data/AAAA-MM-DD.json` **só na pasta `data/`**. Ignore subpastas (`data/testes/`,
   `data/enviados/`, `data/falhas/`) e os arquivos `-news.json`. Exemplo: `ls data/????-??-??.json`.
2. O pregão é o **mais recente** desses arquivos (abaixo, `<pregao>`).
3. **Pare sem escrever nada e sem commit** se qualquer um destes for verdade:
   - não há nenhum `data/AAAA-MM-DD.json`;
   - `data/<pregao>-news.json` não existe;
   - `edicao/<pregao>.md` já existe (a edição desse pregão já foi escrita);
   - `data/enviados/<pregao>.json` já existe (a edição desse pregão já foi enviada).

   Não volte para pregões mais antigos: o envio só manda o pregão mais recente.

## 2. Arquivos de entrada

- `data/<pregao>.json`: números do pregão (contrato descrito no CLAUDE.md).
- `data/<pregao>-news.json`: manchetes já filtradas, com `contexto_geral` e `usuarios` (um bloco por código de usuário).

Leia só esses dois arquivos. **Não pesquise na web** e não use nenhuma outra fonte, nem o que você
sabe sobre o mercado: só o que está nos arquivos.

## 3. Arquivo de saída: `edicao/<pregao>.md`

Exatamente neste formato, sem título, sem nada antes do primeiro `##`:

```markdown
## Geral

Parágrafo 1.

Parágrafo 2.

Parágrafo 3.

## 26980a9bf7

Parágrafo sobre um grupo de ativos desse usuário.

Parágrafo sobre outro grupo.
```

- `## Geral`: 3 parágrafos sobre o mercado no pregão.
- Uma seção `## <código>` para **cada** código em `usuarios` com `"texto_claude": true`, com o código
  copiado exatamente como está no arquivo. 2 a 4 parágrafos por usuário. Usuários com `false` não têm seção.
- Nunca escreva nomes de pessoas nem cite, numa seção, ativos ou códigos de outro usuário.

## 4. O que escrever

O leitor recebe antes um **card com todos os números** (preços, pontos, variações, dólar, Selic,
IPCA) e depois uma lista de manchetes. O seu texto **não repete números**: ele conta a história do
dia, ligando os movimentos ao noticiário.

**Geral** (3 parágrafos de 3 a 5 frases)
- Pregão de referência: campo `pregao`. Escreva "no pregão de quarta-feira (28/10)", nunca "hoje".
- Abra com o tom do dia para a bolsa (alta, queda, estabilidade), usando a direção do Ibovespa em
  `indices` (sinal de `var_dia_pct`), sem citar o número.
- Desenvolva os assuntos de `contexto_geral` (cada manchete tem um `tema`: Juros, Câmbio, Fiscal,
  Exterior...), um ou dois temas por parágrafo, ligando um ao outro quando o noticiário permitir.
- Se `status` for `sem_pregao`, diga que não houve pregão no último dia útil. Se for `parcial`,
  diga que parte dos dados não foi coletada (sem listar tickers).

**Seção de cada usuário** (`usuarios.<código>`, 2 a 4 parágrafos de 2 a 4 frases)
- Fale só dos `tickers` desse usuário. Agrupe por assunto (ex.: bancos, varejo, petróleo), não um
  parágrafo por ticker.
- Comece pelos ativos de `movimentos` (maiores altas e baixas dele), dizendo se subiram ou caíram
  (direção vinda do JSON, sem o número), e use as manchetes de `movimentos[].noticias` e, quando
  ajudar, as de `contexto` desse usuário.
- Ativo de `movimentos` sem manchete: "sem notícia específica".
- Escreva o nome da empresa com o ticker entre parênteses: "o Bradesco (BBDC4)".

## 5. Regras

1. **Sem preços, pontos nem variações percentuais**: estão no card. A direção (subiu, caiu,
   ficou estável) vem do sinal no JSON. Outros números só se estiverem no **título de uma manchete
   citada com link**, exatamente como lá (ex.: "lucro de R$ 7,1 bilhões, segundo a [Suno](url)").
   Nunca calcule, estime nem traga número de fora dos arquivos.
2. **Todo "porquê" tem link de uma manchete do arquivo**, no formato `[nome da fonte ou título
   curto](url)`, com a URL copiada exatamente do campo `url` (não encurte nem altere). Atribua à
   notícia, sem afirmar a causa por conta própria: "em meio à [decisão do Fed sobre juros](url)",
   "segundo o [InfoMoney](url)". Não acrescente fatos que não estão no título (cargo de pessoa,
   valores, datas). Nunca invente link.
3. **Fatos, sem opinião:** nada de "ótimo", "preocupante", "oportunidade", previsões ("deve subir"),
   nem qualquer sugestão de comprar, vender ou manter.
4. **Tamanho:** leitura de 2 a 3 minutos para cada leitor (Geral + a seção dele): cerca de 250 a 350
   palavras na Geral e 120 a 250 por usuário. No máximo 2 links por parágrafo: os links são longos e
   cada mensagem do Discord tem limite de 2.000 caracteres.
5. **Português do Brasil**, tom de jornal, frases diretas. **Sem travessões** (— ou –): use vírgula,
   ponto, dois-pontos ou parênteses.

Antes de salvar, confira: não há preço nem variação no texto; todo número que sobrou está no título
de uma manchete linkada; cada link aparece no arquivo de notícias; nenhuma seção cita ativo de outro
usuário; não há travessão.

## 6. Commit

1. `git add -f edicao/<pregao>.md` (a pasta `edicao/` é ignorada no template; por isso o `-f`).
2. `git commit -m "Edição do pregão <pregao>"`.
3. `git push origin HEAD:main`. Se for recusado, dê push na branch em que a sessão está
   (`git push -u origin HEAD`); se a sessão estiver na main, crie antes uma branch
   `claude/edicao-<pregao>`. O workflow de envio dispara com push em `edicao/**` em qualquer
   branch e lê o arquivo de lá. Confirme que o push deu certo.

Não altere nenhum outro arquivo do repositório.
