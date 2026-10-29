# Tarefa: escrever o texto da edição do dia

Você escreve o texto opcional da newsletter diária do mercado brasileiro (B3). Esta tarefa roda
às 8h (horário de Brasília), depois da coleta das 7h30. O envio pelo Discord é feito por outro
workflow, que dispara quando o seu arquivo chega ao repositório. Você **não** envia nada.

Projeto informativo: o texto nunca sugere comprar, vender ou manter ativos.

## 1. Arquivos de entrada

Use a data de hoje em America/Sao_Paulo, no formato `AAAA-MM-DD` (abaixo, `<data>`).

- `data/<data>.json`: números do pregão (contrato descrito no CLAUDE.md).
- `data/<data>-news.json`: manchetes já filtradas, com `contexto_geral` e `usuarios` (um bloco por código de usuário).

**Se algum dos dois não existir, pare aqui:** não escreva nenhum arquivo, não faça commit.

Leia só esses dois arquivos. **Não pesquise na web** e não use nenhuma outra fonte, nem o que você
sabe sobre o mercado: só o que está nos arquivos.

## 2. Arquivo de saída: `edicao/<data>.md`

Exatamente neste formato, sem título, sem nada antes do primeiro `##`:

```markdown
## Geral

Parágrafo 1.

Parágrafo 2.

## 26980a9bf7

Parágrafo sobre os ativos desse usuário.
```

- `## Geral`: 2 a 3 parágrafos sobre o mercado no pregão.
- Uma seção `## <código>` para **cada** código em `usuarios` com `"texto_claude": true`, com o código
  copiado exatamente como está no arquivo. 1 parágrafo por usuário. Usuários com `false` não têm seção.
- Nunca escreva nomes de pessoas nem cite, numa seção, ativos ou códigos de outro usuário.

## 3. O que escrever

**Geral**
- Pregão de referência: campo `pregao`. Escreva "no pregão de dd/mm", nunca "hoje" para o pregão.
- Ibovespa: pontos e variação no dia, na semana e no mês, de `indices`.
- Dólar PTAX, Selic meta e IPCA mensal, de `macro`, com a data ou o mês de referência.
- Contexto: as manchetes de `contexto_geral` (cada uma tem um `tema`).
- Se `status` for `sem_pregao`, diga que não houve pregão no último dia útil. Se for `parcial`,
  diga que parte dos dados não foi coletada (sem listar tickers).

**Seção de cada usuário** (`usuarios.<código>`)
- Fale só dos `tickers` desse usuário, com os números de `ativos` no JSON do dia.
- Destaque os ativos de `movimentos` (maiores altas e baixas dele).
- Para explicar um movimento, use as manchetes de `movimentos[].noticias` ou de `contexto` desse
  usuário. Se o ativo não tiver manchete, escreva "sem notícia específica".

## 4. Regras

1. **Todo número vem do JSON**, exatamente como está (preço, pontos, variações, Selic, IPCA, dólar).
   Não calcule números novos, não arredonde de outro jeito, não estime.
   Formato brasileiro: vírgula decimal, sinal nas variações (`+2,25%`, `-0,53%`), pontos com
   separador de milhar (`171.006 pontos`).
2. **Todo "porquê" tem link de uma manchete do arquivo**, no formato `[título curto](url)`, com a
   URL copiada exatamente do campo `url` (não encurte nem altere). Atribua à notícia, sem afirmar a
   causa por conta própria: "em meio à [decisão do Fed sobre juros](url)", "segundo o [InfoMoney](url)".
   Sem manchete para aquele ponto: "sem notícia específica". Nunca invente link.
3. **Fatos, sem opinião:** nada de "ótimo", "preocupante", "oportunidade", previsões ("deve subir"),
   nem qualquer sugestão de comprar, vender ou manter.
4. **Tamanho:** leitura de 2 a 3 minutos para cada leitor (Geral + a seção dele): cerca de 200 a 300
   palavras na Geral e 80 a 150 por usuário. No máximo 2 links por parágrafo: os links são longos e
   cada mensagem do Discord tem limite de 2.000 caracteres.
5. **Português do Brasil**, frases diretas. **Sem travessões** (— ou –): use vírgula, ponto,
   dois-pontos ou parênteses.

Antes de salvar, confira: cada número aparece no JSON; cada link aparece no arquivo de notícias;
nenhuma seção cita ativo de outro usuário; não há travessão.

## 5. Commit

1. `git add -f edicao/<data>.md` (a pasta `edicao/` é ignorada no template; por isso o `-f`).
2. `git commit -m "Edição <data>"`.
3. `git push`. Se não puder dar push na branch principal, dê push numa branch própria: o workflow
   de envio dispara com push em `edicao/**` em qualquer branch e lê o arquivo de lá.

Não altere nenhum outro arquivo do repositório.
