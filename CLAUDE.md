# Newsletter diária do mercado brasileiro (B3)

## O que é

Todo dia útil, coleta cotações da B3 e indicadores do Banco Central em um JSON e envia por **DM no Discord**, **para cada usuário**, um card com os números dos ativos dele e um texto com destaques e notícias relacionadas. (Até 28/10/2026 o envio era pelo Telegram; ninguém do grupo usa Telegram.)

São dois repositórios com o mesmo código:

- **`newsletter-mercado` (público, template):** só código e exemplos. Nunca recebe dados de usuários. `usuarios.yml` e `data/*.json` ficam no `.gitignore`. O workflow existe, mas não roda em repositório público (trava de privacidade).
- **`newsletter-project` (privado, produção):** clone do público, com o público como remote `template` para puxar atualizações (`git fetch template && git merge template/main`). Os usuários ficam no Secret `USUARIOS_YAML`. O Actions roda aqui e commita os JSONs com `git add -f`.

Nada pessoal pode ficar fixo no código: usuários, discord_ids e tokens só em `usuarios.yml` local, `.env` ou Secrets.

## Arquitetura

```
[GitHub Actions no repo privado, dias úteis 18h30 BRT]
   collect.py -> união dos tickers de todos os usuários (cada um buscado uma vez)
                 brapi (cotações) + Banco Central SGS (Selic, IPCA, dólar)
        └-> data/AAAA-MM-DD.json  (commitado só no repo privado)
   notify.py -> para cada usuário:
                recorte do JSON (só os tickers dele)
                + card.py (PNG) + news.py (manchetes; contexto: temas dele + motores de temas.yml)
                -> DM no Discord (bot) para o discord_id dele

[Agente de narrativa, ~19h, fora deste repo]
   lê o JSON do dia + pesquisa notícias -> escreve a edição
```

Princípio: **API mede, notícia explica.** Todo número vem do JSON. As manchetes do `news.py` são só contexto relacionado: nunca são fonte de número nem explicação de causa.

## Estrutura

```
.github/workflows/coleta.yml   Actions: trava de privacidade -> coleta -> commit do JSON -> envio
data/                          um JSON por dia útil (no público: só .gitkeep; *.json ignorado)
usuarios.py                    lê usuários de USUARIOS_YAML ou usuarios.yml
usuarios.example.yml           exemplo com dados fictícios (o real, usuarios.yml, fica fora do Git)
collect.py                     coletor
card.py                        gera out/card-AAAA-MM-DD[-<código>].png (Jinja2 + Playwright)
templates/card.html            template do card
news.py                        manchetes relacionadas -> out/noticias-AAAA-MM-DD[-<código>].json
notify.py                      uma edição por usuário, por DM no Discord (--previa só gera e mostra)
ativar_discord.py              ativação única do bot (conecta ao Gateway uma vez; usa websocket-client)
out/                           cards e notícias gerados (fora do Git); <código> = hash curto do discord_id
fontes.txt                     fontes de notícia aceitas; uma por linha, # é comentário
temas.yml                      motores do "Contexto do mercado" (busca + palavras exigidas no título)
requirements.txt               requests, python-dotenv, jinja2, playwright, pyyaml
.env                           BRAPI_TOKEN, DISCORD_BOT_TOKEN (local, fora do Git)
```

## Regras invioláveis

- **Nunca leia, imprima, logue ou commite o `.env`, `usuarios.yml` ou o valor de tokens e discord_ids.** Os scripts carregam o `.env` via python-dotenv; no Actions tudo vem de Secrets.
- **Logs só com contagens.** Nunca discord_id, nome, tickers ou temas de usuário, nem consultas de notícia. Exemplos: `Usuários: 3 | enviados: 2 | falhas: 1`, `ativos: 9/9`. Erros detalhados por ticker vão só para o JSON (`erros`), que só existe no repo privado. A única exceção é `notify.py --previa`, que mostra o conteúdo para o dono conferir localmente e nunca roda no Actions.
- **Um usuário não vê dados de outro.** Card, destaques e erros de cada edição só citam os tickers dele (ver `filtrar_para_usuario`). Arquivos em `out/` são nomeados por `codigo_do_usuario` (hash curto do discord_id), nunca pela posição na lista: se a ordem mudar entre a prévia e o envio, a posição faria um usuário receber as notícias de outro. Ao reaproveitar notícias, o `notify.py` também confere se os ativos do arquivo são do usuário.
- **O workflow só processa dados em repositório privado.** Ele consulta a visibilidade pela API, porque em execuções agendadas (`schedule`) o `github.event` não traz `repository`. Não troque por `if: github.event.repository.private`, que deixaria a coleta agendada sem rodar.
- Falha em um ticker não derruba a coleta: registra em `erros` e segue. Falha em um usuário não impede os outros.
- O JSON é sempre gravado, mesmo com erros, para a edição poder avisar o que falhou.
- Projeto informativo: nada no código, README ou saídas sugere comprar, vender ou manter ativos.
- **Privacidade e custo zero são prioridades.** Nada pode exigir plano pago (ex.: GitHub Pages em repo privado precisa de Pro). Visualização é por DM no Discord, que é privada e grátis. Nenhum outro membro ou administrador do servidor vê as DMs (ao contrário de canais privados, que o dono e os administradores do servidor sempre veem).
- O token do bot vai no header `Authorization: Bot ...`: nunca imprimir headers, URLs com ids nem exceção crua do `requests`.

## Usuários (`usuarios.py`)

O YAML vem da variável `USUARIOS_YAML`, quando definida (Secret no Actions); senão, do arquivo `usuarios.yml`. Formato (ver `usuarios.example.yml`):

```yaml
usuarios:
  - nome: Ana
    discord_id: "111111111111111111"   # entre aspas
    tickers: [PETR4, VALE3]
    temas: [Juros, eleição]            # opcional
```

- Entradas sem `discord_id` (só dígitos) ou sem lista de `tickers` são ignoradas; o log mostra só quantas.
- Erro de YAML mostra só o tipo do erro, porque a mensagem completa pode citar trechos da configuração.
- `nome` serve só para organizar o arquivo: não aparece em log nem na mensagem.
- `discord_id`: no Discord, Configurações > Avançado > Modo desenvolvedor; botão direito na pessoa > "Copiar ID do usuário". O dono copia; a pessoa não precisa fazer nada.
- Para receber a DM, a pessoa precisa estar num servidor em comum com o bot e aceitar DMs de membros do servidor (padrão do Discord). Se não aceitar, a falha conta no log (código 50007) e os outros recebem normalmente.
- `temas`: o nome de um motor de `temas.yml` (ex.: `Juros`) ou um assunto livre (ex.: `eleição`). Entram primeiro no contexto.
- O cadastro é manual. Comandos no bot exigiriam um servidor ligado o tempo todo, o que fere o custo zero. O dono do bot e do repo privado vê a configuração de todos.

## brapi (verificado em 28/10/2026, docs: https://brapi.dev/docs)

Base: `https://brapi.dev/api/v2/stocks`. Autenticação: header `Authorization: Bearer <token>`.

- **Cotação:** `GET /quote?symbols=PETR4`. Resposta: `results[].data` com `shortName`, `longName`, `regularMarketPrice`, `regularMarketChangePercent`, `regularMarketTime` (ISO UTC). Em ações, `shortName` é só o ticker; o `nome` do JSON usa `longName`.
- **Histórico:** `GET /historical?symbols=PETR4&range=3mo&interval=1d&sortOrder=asc`. Resposta: `results[].data.historicalDataPrice[]` com `date`, `open`, `high`, `low`, `close`, `volume`, `adjustedClose`. `date` é unix em segundos, meia-noite BRT (o código também aceita ISO). O histórico **já inclui o pregão do dia** após o fechamento.
- **Sem token** respondem: PETR4, VALE3, ITUB4, MGLU3. Use-os para inspecionar o formato real.
- **Plano gratuito:** 15.000 req/mês, 1 ticker por chamada, 1 requisição simultânea, histórico de até 3 meses, atraso ~30 min. Por isso: um ticker por vez, pausa de ~1,5 s entre chamadas. São 2 chamadas por ticker por dia, cerca de 44 por mês por ticker: o limite comporta uns 300 tickers distintos na união dos usuários.
- **Ibovespa:** `^BVSP` funciona no v2 (quote e historical), mas **exige token** (sem token: 401 `MISSING_TOKEN`).
- Erros: 401 token inválido, 403 fora do plano, 429 limite (respeitar `Retry-After`).
- Existe a API antiga `/api/quote/{ticker}`, mas usar a v2.

## Banco Central (SGS, gratuito, sem token)

`https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/1?formato=json`

- 432: Selic meta (% a.a.)
- 433: IPCA mensal (%)
- 1: dólar comercial venda (PTAX, R$)

Instável: respostas de ~15 s e 502 intermitente; o coletor tenta 3 vezes por série. A série 432 pode vir com data futura (vigência até a próxima reunião do Copom).

## Discord (DM do bot, uma edição por usuário)

API REST `https://discord.com/api/v10`, header `Authorization: Bot <DISCORD_BOT_TOKEN>` e `User-Agent: DiscordBot (url, versão)`. Não usa biblioteca de Discord: só `requests`.

- **Abrir a DM:** `POST /users/@me/channels` com `{"recipient_id": discord_id}`. Devolve o canal de DM; se ele já existir, devolve o mesmo.
- **Mensagem:** `POST /channels/{canal}/messages` com `flags: 4` (SUPPRESS_EMBEDS, sem prévia de links) e `allowed_mentions: {"parse": []}`. O card vai como multipart (`payload_json` + `files[0]`), com o arquivo em bytes, para poder reenviar se vier 429.
- **429:** espera o `retry_after` do corpo e tenta até 3 vezes. Pausa de 0,5 s entre mensagens.
- **Ativação única:** o Discord exige que um bot novo se conecte ao Gateway uma vez antes de enviar mensagens. Para isso existe `python ativar_discord.py`, que roda uma vez, na máquina local, e precisa de `pip install websocket-client` (fora do `requirements.txt`).
- **Criação do bot:** Developer Portal → New Application.
  - Installation: Install Link = None.
  - Bot: desmarcar Public Bot e gerar o token; nenhum Privileged Intent.
  - OAuth2 → URL Generator: só o scope `bot`, sem permissões; com a URL, convidar o bot para o servidor do grupo.

Para cada usuário, `notify.py` recorta o JSON (`filtrar_para_usuario`):
- só os ativos dele;
- só os erros dos tickers dele, mais os de macro e índices;
- `status` recalculado: `sem_pregao` vale para todos; `parcial` se houver erro ou ativo sem dado de hoje entre os dele.

Depois envia por DM, nesta ordem:

1. **Mensagem com o card anexado** (`card.py`), arquivo `mercado-AAAA-MM-DD.png`: só números do recorte. Ibovespa, dólar PTAX, Selic, IPCA e tabela dos ativos (fechamento, dia, semana, mês) ordenada pela variação do dia. Aviso no topo se `status` for `parcial` ou `sem_pregao`. Rodapé: "Dados: brapi e Banco Central | coletado em X | informativo, não é recomendação".
   - Visual de terminal financeiro: fundo escuro, números em fonte mono tabular alinhados à direita, verde (`#2cb5a0`) e vermelho (`#f0605d`) **só nas variações**, sempre com sinal +/−. O par foi validado para daltonismo e contraste. Sem gradientes.
   - Playwright/Chromium, viewport de 1080 px, `device_scale_factor=2`, screenshot só do `#card`. Sem recursos externos no template.
2. **Mensagens de texto** em Markdown do Discord: avisos de status, linha do Ibovespa e as 2 maiores altas e 2 maiores baixas **entre os ativos do usuário**:
   ```
   ▲ **WEGE3** +2,25%
   - [Manchete](<link>) (fonte)
   ```
   - Sem manchete: "sem notícia específica"; busca com falha: "notícias indisponíveis".
   - Depois vem "Contexto do mercado", com uma manchete por tema e o rótulo do tema (`- **Juros** · [Manchete](<link>) (fonte)`). No fim, uma nota em texto pequeno (`-# `) diz que as manchetes são **relacionadas, não a causa**. O texto nunca afirma causalidade.
   - Título, fonte e tema passam por `escapar` (Markdown do Discord). Só links `https`, com `)` e espaço codificados na URL.
   - Limite: **2000 caracteres por mensagem, contando as URLs** (os links do Google News têm até ~600 caracteres). `dividir_em_mensagens` junta blocos (cabeçalho, cada ativo, contexto, nota) até o limite. Bloco maior que o limite começa numa mensagem nova e é quebrado por linha, para o título da seção não ficar sozinho. Na prática, são 3 ou 4 mensagens por edição.

Falhas:
- Notícias ou RSS com problema: a edição segue sem manchetes.
- Card com problema: o texto é enviado mesmo assim.
- Erro do Discord com um usuário (DM bloqueada, id errado): os outros continuam.

No fim, o log mostra só `Usuários | enviados | falhas | sem card` e os motivos das falhas, por exemplo `HTTP 403 ao enviar card: 50007 Cannot send messages to this user`. O script sai com código 1 se houver falha ou card ausente.

Prévia e envio:
- `python notify.py --previa`: gera cards e notícias de todos e mostra as mensagens, sem enviar.
- `python notify.py --reusar-noticias`: envia reaproveitando `out/noticias-AAAA-MM-DD-<código>.json` da prévia, sem buscar de novo.

No Actions, instalar o navegador com `python -m playwright install --with-deps chromium`.

### Notícias (`news.py`)

- **Fonte:** Google News RSS, `https://news.google.com/rss/search?q=<busca> when:1d&hl=pt-BR&gl=BR&ceid=BR:pt-419`.
  - Não usa token; o XML é lido com `xml.etree` da biblioteca padrão.
  - Itens: `title` ("Manchete - Fonte", o sufixo é removido), `link` (redirecionamento do Google, com até ~600 caracteres), `pubDate`, `source`.
- **Cache por execução** (`_cache_rss`): usuários com o mesmo ativo ou tema não repetem a busca.
- **Busca por ativo:** nome limpo + ticker. O nome limpo sai do `nome` sem SA/S.A./Pfd/ON/PN/Holding e sem o que vem depois de " - ". Exemplo: "Itau Unibanco Holding SA Pfd" vira "Itau Unibanco ITUB4".
- **Contexto do mercado** (`fila_de_contexto`): **4 manchetes, uma por tema**, cada uma com o rótulo do tema. A fila tem esta ordem:
  1. **Temas do usuário.** Se o tema tiver o nome de um motor de `temas.yml` (ex.: `Juros`), usa o motor. Se for assunto livre, a busca é `<tema> mercado` ("eleição" sozinha traz política em geral) e o título precisa citar o radical do tema ("eleição" casa com "eleições").
  2. **Motores de `temas.yml`** (Bolsa, Juros, Câmbio, Inflação, Fiscal, Política, Exterior, Commodities), ordenados por **volume do dia**: quantas manchetes válidas o motor tem nas últimas 24h (`volume_do_dia`). É uma medida simples de quanto o assunto está em pauta, não de impacto no preço.
  - Cada motor tem `busca`, uma consulta ao Google News que aceita OR e aspas, e `palavras`: o título precisa ter uma palavra que **comece** com um dos termos, sem diferenciar maiúsculas e acentos. Evite termos curtos que casem com palavras comuns (ex.: "DI" casaria com "dia").
  - Sem `temas.yml` e sem temas do usuário, a busca é "Ibovespa", sem exigir citação.
  - Como o agrupamento de manchetes parecidas vale para a mensagem toda, o mesmo fato não aparece em dois temas.
- **Seleção dos ativos:** só ativos com `dado_de_hoje`. Altas são as variações > 0 e baixas as < 0; num dia sem nenhuma alta, não há ▲.
- **Escolha das manchetes:** até 2 por ativo e 1 por tema do contexto, na ordem do Google. Cada manchete passa por `motivo_descarte`, e **o primeiro motivo que se aplicar** é o registrado:
  1. `sem data` / `mais de 24h`: o `pubDate` é conferido de novo; o `when:1d` sozinho não basta.
  2. `fonte fora da lista`: a lista fica em **`fontes.txt`**. A fonte é aceita se o nome começar por um item da lista, sem diferenciar maiúsculas e acentos ("Valor" aceita "Valor Investe"). Sem o arquivo, não há filtro de fonte.
  3. `não cita o ativo ou tema no título`:
     - Para ativo, vale o ticker (qualquer caixa), o nome limpo ou um apelido de `APELIDOS` em `news.py` (Petrobras, Itau, Bradesco, PetroRio, Magalu…). Nomes são comparados com caixa exata, para "Vale" não casar com "vale". **Ao incluir um ticker cujo nome na imprensa difere do `longName`, acrescente o apelido.**
     - Para tema, vale o radical do tema.
  4. `página de cotação` ("BBDC4 - Banco Bradesco - Resultados, Dividendos, Cotação…").
  5. `especulativo`: título terminado em "?", ou com "pode disparar", "vale a pena", "comprar" ou "ações para".
  6. `tom de recomendação`: "recomenda", "vender", "preço-alvo", "potencial de valorização". Segue a regra de projeto informativo.
  7. `repetida ou parecida`: mesmo link, ou título do mesmo fato que outro já usado na mensagem (`parecidas`). Conta como parecido:
     - texto com similaridade ≥ 0,8 (`SequenceMatcher`); ou
     - palavras-chave em comum ≥ 50% do título menor, com pelo menos 3 palavras.
     As palavras-chave são radicais de 4 letras ("Vamos" e "VAMO3" viram "vamo") e números sem separador ("5,34" vira "534"), sem palavras vazias. Fica a primeira manchete de cada fato.
- Sem manchete válida para o ativo: "sem notícia específica". Isso é esperado com os filtros rígidos.
- **Saída:** `out/noticias-AAAA-MM-DD-<código>.json` (`{"data", "movimentos": [{"ticker", "var_dia_pct", "busca_ok", "noticias": [...]}], "contexto": [{..., "tema"}], "descartes": [{"busca", "motivo", "titulo", "fonte"}]}`). `python news.py` é um diagnóstico com todos os ativos do JSON e sem temas: imprime só contagens por motivo e grava os detalhes em `out/noticias-AAAA-MM-DD.json`.

## Contrato do JSON de saída

O agente de narrativa depende deste formato. Mudanças aqui precisam ser intencionais. O JSON do dia tem **todos** os tickers da união dos usuários; o recorte por usuário é feito só na hora do envio.

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

Cada erro começa por `<origem>:`, que é o ticker ou o nome da série macro. O recorte por usuário usa esse prefixo.

Regras de `status`:
- `sem_pregao`: o Ibovespa não tem cotação com data de hoje (feriado ou fim de semana).
- `parcial`: há erros ou algum ativo sem dado de hoje.
- `ok`: o resto.

Variações de semana e mês seguem o **padrão de calendário da imprensa** (desde 28/10/2026; antes eram 5 e 21 pregões):
- semana: preço atual vs. último fechamento do histórico **antes da segunda-feira** da semana da cotação (normalmente a sexta anterior);
- mês: preço atual vs. último fechamento **antes do dia 1º** do mês da cotação (último pregão do mês anterior).

A referência é a data da cotação (`horario_cotacao`), não o relógio: em dia útil é hoje; em feriado ou fim de semana, o último pregão. Como só entram pontos anteriores à segunda-feira ou ao dia 1º, não importa se o histórico já traz o pregão do dia. O histórico de 3 meses cobre os dois casos.

## GitHub Actions (`coleta.yml`)

Roda em dias úteis às 18h30 BRT (`30 21 * * 1-5`) e também por `workflow_dispatch`.

1. Job `visibilidade`: `gh api repos/$GITHUB_REPOSITORY --jq .private`.
2. Job `coleta`, só se o resultado for `true`:
   - Python 3.12 e Chromium;
   - `collect.py`;
   - `git add -f data/*.json`, commit e push;
   - `notify.py`.

Secrets do repo privado: `BRAPI_TOKEN`, `DISCORD_BOT_TOKEN`, `USUARIOS_YAML` (o conteúdo inteiro do YAML).

## Convenções

- Python 3.12. Dependências só `requests`, `python-dotenv`, `jinja2` e `playwright` (estas duas só para o card) e `pyyaml` (usuários).
- Funções pequenas, nomes e comentários em português.
- Desenvolvimento local em Windows (PowerShell); produção em `ubuntu-latest` no Actions. Paths com `pathlib`, arquivos com `encoding="utf-8"`.
- Fuso: America/Sao_Paulo (UTC-3) em datas e no nome do arquivo.
- O dono do repo está aprendendo: antes de escrever código, explique o plano em poucas linhas. Respostas curtas e diretas.

## Roadmap

1. [x] Conta brapi e token
2. [x] Repositório e estrutura
3. [x] `collect.py`
4. [x] Rodar local e validar números
5. [ ] GitHub Actions: `coleta.yml` escrito; falta criar o repo privado, cadastrar os Secrets e acompanhar a primeira execução
6. [ ] Camada de narrativa (fora do repo)
7. [ ] README do template (repo privado próprio ou entrar como usuário no prod; `usuarios.example.yml`)

Evoluções depois da v1: juros futuros (DI) como termômetro de risco, variação no ano com os JSONs acumulados, edição semanal.
