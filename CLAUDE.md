# Newsletter diária do mercado brasileiro (B3)

## O que é

Repositório template que gera, todo dia útil, um JSON com cotações de ações da B3 e indicadores do Banco Central. Esse JSON alimenta uma newsletter escrita depois por um agente (fora deste repo).

É um **template público**: outras pessoas criam uma cópia, colocam o próprio token da brapi como Secret e editam o `tickers.txt`. Nada pessoal pode ficar fixo no código.

## Arquitetura

```
[GitHub Actions, dias úteis 18h30 BRT]
   collect.py -> brapi (cotações) + Banco Central SGS (Selic, IPCA, dólar)
        └-> data/AAAA-MM-DD.json  (commitado no próprio repo)

[Agente de narrativa, ~19h, fora deste repo]
   lê o JSON do dia + pesquisa notícias -> escreve a edição
```

Princípio: **API mede, notícia explica.** Este repo cuida só da medição. Todo número da newsletter vem do JSON.

## Estrutura

```
.github/workflows/coleta.yml   agendamento no GitHub Actions
data/                          um JSON por dia útil
collect.py                     script coletor
tickers.txt                    um ticker por linha; linhas com # são comentário
requirements.txt               requests, python-dotenv
.env                           BRAPI_TOKEN=... (local, fora do Git)
```

## Regras invioláveis

- **Nunca leia, imprima, logue ou commite o `.env` ou o valor do token.** O script carrega o `.env` via python-dotenv; no Actions o token vem do Secret `BRAPI_TOKEN`.
- Falha em um ticker não derruba a coleta: registra em `erros` e segue.
- O JSON é sempre gravado, mesmo com erros, para a edição poder avisar o que falhou.
- Projeto informativo: nada no código, README ou saídas sugere comprar, vender ou manter ativos.

## brapi (verificado em 28/10/2026, docs: https://brapi.dev/docs)

Base: `https://brapi.dev/api/v2/stocks`. Autenticação: header `Authorization: Bearer <token>`.

- **Cotação:** `GET /quote?symbols=PETR4`. Resposta: `results[].data` com `shortName`, `longName`, `regularMarketPrice`, `regularMarketChangePercent`, `regularMarketTime` (ISO UTC). Em ações, `shortName` é só o ticker; o `nome` do JSON usa `longName`.
- **Histórico:** `GET /historical?symbols=PETR4&range=3mo&interval=1d&sortOrder=asc`. Resposta: `results[].data.historicalDataPrice[]` com `date`, `open`, `high`, `low`, `close`, `volume`, `adjustedClose`. `date` é unix em segundos, meia-noite BRT (o código também aceita ISO). O histórico **já inclui o pregão do dia** após o fechamento.
- **Sem token** respondem: PETR4, VALE3, ITUB4, MGLU3. Use-os para inspecionar o formato real.
- **Plano gratuito:** 15.000 req/mês, 1 ticker por chamada, 1 requisição simultânea, histórico de até 3 meses, atraso ~30 min. Por isso: um ticker por vez, pausa de ~1,5 s entre chamadas.
- **Ibovespa:** `^BVSP` funciona no v2 (quote e historical), mas **exige token** (sem token: 401 `MISSING_TOKEN`).
- Erros: 401 token inválido, 403 fora do plano, 429 limite (respeitar `Retry-After`).
- Existe a API antiga `/api/quote/{ticker}`, mas usar a v2.

## Banco Central (SGS, gratuito, sem token)

`https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/1?formato=json`

- 432: Selic meta (% a.a.)
- 433: IPCA mensal (%)
- 1: dólar comercial venda (PTAX, R$)

Instável: respostas de ~15 s e 502 intermitente; o coletor tenta 3 vezes por série. A série 432 pode vir com data futura (vigência até a próxima reunião do Copom).

## Contrato do JSON de saída

O agente de narrativa depende deste formato. Mudanças aqui precisam ser intencionais.

```json
{
  "data": "2026-10-28",
  "coletado_em": "2026-10-28T18:30:12-03:00",
  "status": "ok | parcial | sem_pregao",
  "indices": [ <ativo> ],
  "ativos": [ <ativo> ],
  "macro": {
    "selic_meta": {"data": "dd/mm/aaaa", "valor": 0.0},
    "ipca_mensal": {"data": "dd/mm/aaaa", "valor": 0.0},
    "dolar_ptax_venda": {"data": "dd/mm/aaaa", "valor": 0.0}
  },
  "erros": ["PETR4: mensagem"]
}
```

`<ativo>`: `ticker`, `nome`, `preco`, `var_dia_pct`, `var_semana_pct` (vs. 5 pregões antes), `var_mes_pct` (vs. 21 pregões antes), `horario_cotacao`, `dado_de_hoje` (bool).

Regras de `status`:
- `sem_pregao`: o Ibovespa não tem cotação com data de hoje (feriado ou fim de semana).
- `parcial`: há erros ou algum ativo sem dado de hoje.
- `ok`: o resto.

Variações de semana e mês usam os fechamentos **anteriores a hoje** no histórico (excluir o ponto de hoje, se vier), para não depender de o histórico já ter o pregão do dia.

## Convenções

- Python 3.12. Dependências só `requests` e `python-dotenv`.
- Funções pequenas, nomes e comentários em português.
- Desenvolvimento local em Windows (PowerShell); produção em `ubuntu-latest` no Actions. Paths com `pathlib`, arquivos com `encoding="utf-8"`.
- Fuso: America/Sao_Paulo (UTC-3) em datas e no nome do arquivo.
- O dono do repo está aprendendo: antes de escrever código, explique o plano em poucas linhas. Respostas curtas e diretas.

## Roadmap

1. [x] Conta brapi e token
2. [x] Repositório e estrutura
3. [ ] `collect.py`
4. [ ] Rodar local e validar números
5. [ ] GitHub Actions (`coleta.yml`, Secret `BRAPI_TOKEN`)
6. [ ] Camada de narrativa (fora do repo)
7. [ ] README de template para amigos

Evoluções depois da v1: juros futuros (DI) como termômetro de risco, variação no ano com os JSONs acumulados, edição semanal.
