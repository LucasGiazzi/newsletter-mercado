# Newsletter diária do mercado brasileiro (B3)

## O que é

Repositório template que gera, todo dia útil, um JSON com cotações de ações da B3 e indicadores do Banco Central. Esse JSON alimenta uma newsletter escrita depois por um agente (fora deste repo).

É um **template público**: outras pessoas criam uma cópia, colocam o próprio token da brapi como Secret e editam o `tickers.txt`. Nada pessoal pode ficar fixo no código.

## Arquitetura

```
[GitHub Actions, dias úteis 18h30 BRT]
   collect.py -> brapi (cotações) + Banco Central SGS (Selic, IPCA, dólar)
        └-> data/AAAA-MM-DD.json  (commitado no próprio repo)
   notify.py -> card.py (PNG com os números)
             + news.py (manchetes do Google News RSS) -> texto -> Telegram (bot privado)

[Agente de narrativa, ~19h, fora deste repo]
   lê o JSON do dia + pesquisa notícias -> escreve a edição
```

Princípio: **API mede, notícia explica.** Todo número vem do JSON. As manchetes do `news.py` são só contexto relacionado: nunca são fonte de número nem explicação de causa.

## Estrutura

```
.github/workflows/coleta.yml   agendamento no GitHub Actions
data/                          um JSON por dia útil
collect.py                     script coletor
card.py                        gera out/card-AAAA-MM-DD.png (Jinja2 + Playwright)
templates/card.html            template do card
news.py                        manchetes relacionadas -> out/noticias-AAAA-MM-DD.json
notify.py                      envia card + texto ao Telegram (--previa só gera e mostra)
out/                           cards e notícias gerados (fora do Git)
tickers.txt                    um ticker por linha; linhas com # são comentário
requirements.txt               requests, python-dotenv, jinja2, playwright
.env                           BRAPI_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (local, fora do Git)
```

## Regras invioláveis

- **Nunca leia, imprima, logue ou commite o `.env` ou o valor do token.** O script carrega o `.env` via python-dotenv; no Actions o token vem do Secret `BRAPI_TOKEN`.
- Falha em um ticker não derruba a coleta: registra em `erros` e segue.
- O JSON é sempre gravado, mesmo com erros, para a edição poder avisar o que falhou.
- Projeto informativo: nada no código, README ou saídas sugere comprar, vender ou manter ativos.
- **Privacidade e custo zero são prioridades.** Cada pessoa roda a própria cópia **privada** ("Use this template" → Private; fork de repo público é sempre público). Nada pode exigir plano pago (ex.: GitHub Pages em repo privado precisa de Pro). Visualização é pelo Telegram, que é privado e grátis.
- O token do Telegram vai na URL da API: nunca imprimir URL nem exceção crua do `requests` em `notify.py`.

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

## Telegram (formato híbrido)

Duas mensagens por edição, nesta ordem:

1. **`sendPhoto` com o card** (`card.py`): só números do JSON. Ibovespa, dólar PTAX, Selic, IPCA e tabela dos ativos (fechamento, dia, semana, mês) ordenada pela variação do dia. Aviso no topo se `status` for `parcial` ou `sem_pregao`. Rodapé: "Dados: brapi e Banco Central | coletado em X | informativo, não é recomendação".
   - Visual de terminal financeiro: fundo escuro, números em fonte mono tabular alinhados à direita, verde (`#2cb5a0`) e vermelho (`#f0605d`) **só nas variações**, sempre com sinal +/−. O par foi validado para daltonismo e contraste. Sem gradientes.
   - Playwright/Chromium, viewport de 1080 px, `device_scale_factor=2`, screenshot só do `#card`. Sem recursos externos no template.
2. **`sendMessage` com o texto** (`parse_mode=HTML`, sem preview de link): avisos de status, linha do Ibovespa e, para as 2 maiores altas e as 2 maiores baixas do dia (`news.py`):
   ```
   ▲ WEGE3 +2,25%
     • <a href="link">Manchete</a> (fonte)
   ```
   Sem manchete: "sem notícia específica"; busca com falha: "notícias indisponíveis". Depois vem a seção "Contexto do mercado", com 3 manchetes sobre "Ibovespa", e uma nota dizendo que as manchetes são **relacionadas, não a causa** do movimento. O texto nunca afirma causalidade. Todo texto passa por `html.escape`; só links `https`.
   - Limite: 4096 caracteres **visíveis** (o Telegram conta depois de interpretar o HTML). Se passar, cortam-se manchetes do contexto e depois as do último ativo.

### Notícias (`news.py`)

- Google News RSS, `https://news.google.com/rss/search?q=<busca> when:1d&hl=pt-BR&gl=BR&ceid=BR:pt-419`. Não usa token; o XML é lido com `xml.etree` da biblioteca padrão. Itens: `title` ("Manchete - Fonte", o sufixo é removido), `link` (redirecionamento do Google, com até ~600 caracteres), `pubDate`, `source`.
- Busca por ativo: nome limpo + ticker. O nome limpo sai do `nome` sem SA/S.A./Pfd/ON/PN/Holding e sem o que vem depois de " - ". Exemplo: "Itau Unibanco Holding SA Pfd" vira "Itau Unibanco ITUB4".
- Seleção dos ativos: só ativos com `dado_de_hoje`. Altas são as variações > 0 e baixas as < 0; num dia sem nenhuma alta, não há ▲.
- Escolha das manchetes: até 2 por ativo, publicadas nas últimas 24h, sem repetir título ou link na mensagem. Manchetes que citam o ticker ou o nome no título vêm primeiro.
- **Filtros:** ficam de fora manchetes com tom de recomendação (recomenda, comprar, vender, vale a pena, preço-alvo, potencial de valorização), por causa da regra de projeto informativo, e páginas de cotação ("BBDC4 - Banco Bradesco - Resultados, Dividendos, Cotação…").
- Saída: `out/noticias-AAAA-MM-DD.json` (`{"data", "movimentos": [{"ticker", "var_dia_pct", "busca_ok", "noticias": [...]}], "contexto": [...]}`). Para enviar exatamente o que apareceu na prévia: `python notify.py --noticias out/noticias-AAAA-MM-DD.json`. Sem `--noticias`, o notify busca na hora.

Falhas não bloqueiam o envio: falha no RSS ou nas notícias segue sem manchetes; falha no card ainda envia o texto, e o script sai com código 1. Credenciais só via `.env` ou Secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Para obter o chat_id: mandar mensagem ao bot e abrir `getUpdates`.

No Actions, instalar o navegador com `python -m playwright install --with-deps chromium`.

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

`<ativo>`: `ticker`, `nome`, `preco`, `var_dia_pct`, `var_semana_pct` (vs. último fechamento da semana anterior), `var_mes_pct` (vs. último fechamento do mês anterior), `horario_cotacao`, `dado_de_hoje` (bool).

Regras de `status`:
- `sem_pregao`: o Ibovespa não tem cotação com data de hoje (feriado ou fim de semana).
- `parcial`: há erros ou algum ativo sem dado de hoje.
- `ok`: o resto.

Variações de semana e mês seguem o **padrão de calendário da imprensa** (desde 28/10/2026; antes eram 5 e 21 pregões):
- semana: preço atual vs. último fechamento do histórico **antes da segunda-feira** da semana da cotação (normalmente a sexta anterior);
- mês: preço atual vs. último fechamento **antes do dia 1º** do mês da cotação (último pregão do mês anterior).

A referência é a data da cotação (`horario_cotacao`), não o relógio: em dia útil é hoje; em feriado ou fim de semana, o último pregão. Como só entram pontos anteriores à segunda-feira ou ao dia 1º, não importa se o histórico já traz o pregão do dia. O histórico de 3 meses cobre os dois casos.

## Convenções

- Python 3.12. Dependências só `requests`, `python-dotenv`, `jinja2` e `playwright` (estas duas só para o card).
- Funções pequenas, nomes e comentários em português.
- Desenvolvimento local em Windows (PowerShell); produção em `ubuntu-latest` no Actions. Paths com `pathlib`, arquivos com `encoding="utf-8"`.
- Fuso: America/Sao_Paulo (UTC-3) em datas e no nome do arquivo.
- O dono do repo está aprendendo: antes de escrever código, explique o plano em poucas linhas. Respostas curtas e diretas.

## Roadmap

1. [x] Conta brapi e token
2. [x] Repositório e estrutura
3. [ ] `collect.py`
4. [ ] Rodar local e validar números
5. [ ] GitHub Actions (`coleta.yml`, Secrets `BRAPI_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; coleta → commit → notify)
6. [ ] Camada de narrativa (fora do repo)
7. [ ] README de template para amigos (cópia privada, `tickers.txt` de exemplo, template sem JSONs em `data/`)

Evoluções depois da v1: juros futuros (DI) como termômetro de risco, variação no ano com os JSONs acumulados, edição semanal.
