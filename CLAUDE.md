# Newsletter diária do mercado brasileiro (B3)

## O que é

Todo dia útil, **de manhã**, coleta as cotações do **pregão anterior** na B3 e os indicadores do Banco Central em um JSON e envia por **DM no Discord**, **para cada usuário**, um card com os números dos ativos dele, destaques com notícias relacionadas e, para quem pediu, um texto escrito pelo Claude (módulo opcional). (Até 28/10/2026 o envio era pelo Telegram, às 18h30; ninguém do grupo usa Telegram.)

São dois repositórios com o mesmo código:

- **`newsletter-mercado` (público, template):** só código e exemplos. Nunca recebe dados de usuários. `usuarios.yml`, `data/*.json`, `data/enviados/`, `estado/` e `edicao/` ficam no `.gitignore`. Os workflows existem, mas não rodam em repositório público (trava de privacidade).
- **`newsletter-project` (privado, produção):** clone do público, com o público como remote `template` para puxar atualizações (`git fetch template && git merge template/main`). Os usuários ficam no Secret `USUARIOS_YAML`. Os workflows rodam aqui e commitam os arquivos ignorados com `git add -f`.

Nada pessoal pode ficar fixo no código: usuários, discord_ids e tokens só em `usuarios.yml` local, `.env` ou Secrets.

## Arquitetura

```
[coleta.yml, dias úteis 7h30 BRT, repo privado]
   comandos.py -> lê /add, /del, /list mandados na DM desde a última leitura
        └-> estado/preferencias.json  (listas atualizadas)
   collect.py  -> união dos tickers de todos os usuários (cada um buscado uma vez)
                  brapi (cotações do pregão anterior) + Banco Central SGS (Selic, IPCA, dólar)
        └-> data/AAAA-MM-DD.json
   news.py     -> manchetes de cada usuário (por código) + contexto geral
        └-> data/AAAA-MM-DD-news.json
   commit dos três arquivos

[Tarefa agendada do Claude, 8h, configurada fora do código; OPCIONAL]
   segue prompts/narrativa.md: lê só os dois arquivos do dia, sem pesquisar na web
        └-> edicao/AAAA-MM-DD.md  (commit + push, às vezes numa branch própria)

[envio.yml, repo privado]
   dispara: push em edicao/** (qualquer branch) | 9h BRT (fallback) | manual
   notify.py -> para cada usuário ainda não registrado em data/enviados/AAAA-MM-DD.json:
                card (só os tickers dele) + texto do Claude (se texto_claude e se houver edição)
                + destaques com manchetes -> DM no Discord
        └-> data/enviados/AAAA-MM-DD.json
```

Princípio: **API mede, notícia explica.** Todo número vem do JSON. As manchetes do `news.py` são só contexto relacionado: nunca são fonte de número. O texto do Claude só explica um movimento com link de uma manchete do arquivo do dia.

## Estrutura

```
.github/workflows/coleta.yml   7h30: trava de privacidade -> comandos -> coleta -> manchetes -> commit
.github/workflows/envio.yml    push em edicao/**, 9h ou manual: localiza a edição -> envio -> registro
data/AAAA-MM-DD.json           números do pregão (no público: só .gitkeep; *.json ignorado)
data/AAAA-MM-DD-news.json      manchetes por código de usuário + contexto geral (news.py)
data/enviados/AAAA-MM-DD.json  quem já recebeu a edição do dia, por código (nunca enviar duas vezes)
edicao/AAAA-MM-DD.md           texto do Claude: "## Geral" + "## <código>" (ignorado no público)
prompts/narrativa.md           instruções da tarefa agendada do Claude
estado/preferencias.json       listas alteradas por comando, por código do usuário (ignorado no público)
usuarios.py                    lê usuários de USUARIOS_YAML ou usuarios.yml + preferências
comandos.py                    aplica /add, /del, /list, /ajuda mandados na DM do bot
discord_api.py                 API REST do Discord (abrir DM, enviar e ler mensagens)
usuarios.example.yml           exemplo com dados fictícios (o real, usuarios.yml, fica fora do Git)
collect.py                     coletor
card.py                        gera out/card-AAAA-MM-DD[-<código>].png (Jinja2 + Playwright)
templates/card.html            template do card
news.py                        manchetes relacionadas -> data/AAAA-MM-DD-news.json
notify.py                      uma edição por usuário, por DM no Discord (--previa só gera e mostra)
ativar_discord.py              ativação única do bot (conecta ao Gateway uma vez; usa websocket-client)
out/                           cards gerados (fora do Git); <código> = hash curto do discord_id
fontes.txt                     fontes de notícia aceitas; uma por linha, # é comentário
temas.yml                      motores do "Contexto do mercado" (busca + palavras exigidas no título)
requirements.txt               requests, python-dotenv, jinja2, playwright, pyyaml
.env                           BRAPI_TOKEN, DISCORD_BOT_TOKEN (local, fora do Git)
```

## Regras invioláveis

- **Nunca leia, imprima, logue ou commite o `.env`, `usuarios.yml` ou o valor de tokens e discord_ids.** Os scripts carregam o `.env` via python-dotenv; no Actions tudo vem de Secrets.
- **Logs só com contagens.** Nunca discord_id, nome, tickers ou temas de usuário, nem consultas de notícia. Exemplos: `Usuários: 3 | enviados: 2 | falhas: 1`, `ativos: 9/9`. Erros detalhados por ticker vão só para o JSON (`erros`), que só existe no repo privado. A única exceção é `notify.py --previa`, que mostra o conteúdo para o dono conferir localmente e nunca roda no Actions.
- **Um usuário não vê dados de outro.** Card, destaques, texto e erros de cada edição só citam os tickers dele (ver `filtrar_para_usuario`, em `usuarios.py`).
  - Arquivos em `out/`, manchetes, preferências, registro de envios e seções da edição são indexados por `codigo_do_usuario` (hash curto do discord_id), nunca pela posição na lista: se a ordem mudar, um usuário receberia dados de outro.
  - **Nenhum arquivo do repo tem nome de pessoa ou discord_id**: por isso as seções do texto do Claude são `## <código>`, e não `## <nome>`.
- **Nunca enviar duas vezes no mesmo dia:** `notify.py` pula quem está em `data/enviados/AAAA-MM-DD.json` e grava o registro a cada usuário enviado. O `envio.yml` commita o registro mesmo se o envio falhar no meio, e push e fallback usam o mesmo grupo de execução.
- **Nunca enviar dados de outro dia:** `notify.py` e `news.py` exigem a coleta de hoje (`carregar_json_do_dia`), nunca "o JSON mais recente".
- **Os workflows só processam dados em repositório privado.** Ele consulta a visibilidade pela API, porque em execuções agendadas (`schedule`) o `github.event` não traz `repository`. Não troque por `if: github.event.repository.private`, que deixaria a coleta agendada sem rodar.
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
    texto_claude: true                 # opcional; padrão false
```

- Entradas sem `discord_id` (só dígitos) são ignoradas; o log mostra só quantas. Lista de `tickers` vazia ou ausente é válida: a pessoa recebe as boas-vindas e pode usar `/add`.
- Cada usuário ganha um `codigo` (`codigo_do_usuario`, hash curto do discord_id) que nomeia os arquivos de `out/` e as preferências.
- **A lista de ações vem de `estado/preferencias.json` quando houver** (alterada por `/add` e `/del`); senão, do YAML, que funciona como lista inicial. Para mudar a lista de alguém à mão depois que a pessoa usou comandos, edite o arquivo de preferências no repo privado, não o Secret.
- Erro de YAML mostra só o tipo do erro, porque a mensagem completa pode citar trechos da configuração.
- `nome` serve só para organizar o arquivo: não aparece em log nem na mensagem.
- `discord_id`: no Discord, Configurações > Avançado > Modo desenvolvedor; botão direito na pessoa > "Copiar ID do usuário". O dono copia; a pessoa não precisa fazer nada.
- Para receber a DM, a pessoa precisa estar num servidor em comum com o bot e aceitar DMs de membros do servidor (padrão do Discord). Se não aceitar, a falha conta no log (código 50007) e os outros recebem normalmente.
- `temas`: o nome de um motor de `temas.yml` (ex.: `Juros`) ou um assunto livre (ex.: `eleição`). Entram primeiro no contexto.
- `texto_claude`: só `true` (booleano) liga o texto do Claude para a pessoa; qualquer outro valor conta como falso. Os outros usuários recebem card + destaques, como antes.
- **Quem recebe** é cadastrado à mão no YAML: isso funciona como controle de acesso, porque só as DMs de usuários cadastrados são lidas. **Quais ações** cada um acompanha, a própria pessoa muda pelos comandos (ver abaixo). O dono do bot e do repo privado vê a configuração de todos.

## Comandos na DM (`comandos.py`)

O usuário manda, como mensagem comum na DM do bot, a qualquer hora:

| Comando | Também aceita | Efeito |
|---|---|---|
| `/add PETR4 VALE3` | `!add`, `add`, `adicionar` | adiciona |
| `/del MGLU3` | `delete`, `remover` | remove |
| `/list` | `lista` | só pede a lista (ela já vem em toda resposta) |
| `/ajuda` | `help` | lista os comandos |

- **Leitura uma vez por dia**, no `coleta.yml` às 7h30, antes da coleta. Custo zero; a newsletter é diária, então o que for pedido até as 7h30 já vale na edição da manhã, e o que vier depois vale na do dia útil seguinte. As mensagens ficam guardadas na DM, então nada se perde em fim de semana ou feriado.
- **Por que não são comandos de barra oficiais do Discord:** eles exigem resposta em 3 segundos, o que só um servidor ligado o tempo todo consegue (fere o custo zero). Por isso o bot lê o texto da DM. Em DMs com o bot, o conteúdo das mensagens vem sem o intent privilegiado de Message Content. **Não registre application commands**: o Discord passaria a interceptar `/add` como comando oficial, e sem resposta ele falha.
- Para cada usuário cadastrado:
  1. Abre a DM.
  2. Na primeira vez, manda boas-vindas com a ajuda (`apresentado`).
  3. Lê as mensagens com id maior que o `cursor` (`ler_mensagens`, paginando de 100 em 100) e considera só as do próprio usuário.
  4. Interpreta uma linha por comando; texto que não é comando é ignorado.
  5. Aplica tudo **na ordem em que foi mandado**.
  6. Responde com um resumo: adicionadas, removidas, não encontradas, acima do limite e lista final.
- O `cursor` só avança depois de aplicar e salvar a lista: se algo falhar no meio, os comandos são relidos na próxima execução.
- **Validação:**
  - formato `^[A-Z]{4}\d{1,2}$`;
  - existência na brapi: `/quote` 404 = não existe. Outra falha, como limite ou rede, aceita o ticker e deixa a coleta registrar o erro;
  - máximo de `LIMITE_ACOES` = 20 por pessoa, para proteger a cota da brapi.
- **Lista vazia** (removeu tudo): a pessoa não recebe a edição (`notify.py` conta como "sem ações") até mandar `/add`.
- `estado/preferencias.json`: `{"<codigo>": {"tickers": [...], "cursor": "<id da última mensagem lida>", "apresentado": true}}`. Sem discord_id. Commitado só no repo privado (`git add -f`); no template público, `estado/` fica no `.gitignore`.
- **Rodar `comandos.py` localmente cria um estado local separado do repo privado.** O Actions relê as mesmas mensagens a partir do próprio cursor e responde de novo, incluindo as boas-vindas. Para testar sem duplicar, use um usuário de teste ou apague `estado/` local depois.
- Logs só com contagens: `Usuários: 3 | usuários com comandos: 1 | comandos: 4 | tickers inválidos: 1 | falhas: 0`.

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

API REST `https://discord.com/api/v10`, header `Authorization: Bot <DISCORD_BOT_TOKEN>` e `User-Agent: DiscordBot (url, versão)`. Não usa biblioteca de Discord: só `requests`, em `discord_api.py`, que é compartilhado por `notify.py` e `comandos.py`.

- **Ler mensagens:** `GET /channels/{canal}/messages?after=<id>&limit=100`. O lote vem sem ordem garantida; `ler_mensagens` ordena por id e pagina.

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
- `status` recalculado: `sem_pregao` vale para todos; `parcial` se houver erro ou ativo sem `dado_do_pregao` entre os dele.

Depois envia por DM, nesta ordem:

1. **Mensagem com o card anexado** (`card.py`), arquivo `mercado-<pregão>.png`, legenda "Mercado B3 · fechamento de dd/mm/aaaa": só números do recorte. Ibovespa, dólar PTAX, Selic, IPCA e tabela dos ativos (fechamento, dia, semana, mês) ordenada pela variação do dia. O cabeçalho mostra "FECHAMENTO dd/mm/aaaa" com a data do `pregao`, não a da edição. Aviso no topo se `status` for `parcial` ou `sem_pregao`. Rodapé: "Dados: brapi e Banco Central | coletado em X | informativo, não é recomendação".
   - Visual de terminal financeiro: fundo escuro, números em fonte mono tabular alinhados à direita, verde (`#2cb5a0`) e vermelho (`#f0605d`) **só nas variações**, sempre com sinal +/−. O par foi validado para daltonismo e contraste. Sem gradientes.
   - Playwright/Chromium, viewport de 1080 px, `device_scale_factor=2`, screenshot só do `#card`. Sem recursos externos no template.
2. **Texto do Claude**, só se o usuário tiver `texto_claude: true` **e** existir `edicao/AAAA-MM-DD.md` com a seção `## Geral` (ver "Texto do Claude" abaixo). Vai como "### Panorama do mercado" (a seção Geral) e "### Suas ações" (a seção `## <código>` dele, se houver), um parágrafo por bloco, com o título junto do primeiro parágrafo. O Markdown do Claude (`[título](url)`) é o nativo do Discord: não há conversão.
3. **Destaques** em Markdown do Discord, numa mensagem nova: "Destaques · fechamento de dd/mm", avisos de status, linha do Ibovespa e as 2 maiores altas e 2 maiores baixas **entre os ativos do usuário**:
   ```
   ▲ **WEGE3** +2,25%
   - [Manchete](<link>) (fonte)
   ```
   - Sem manchete: "sem notícia específica"; busca com falha: "notícias indisponíveis".
   - Depois vem "Contexto do mercado", com uma manchete por tema e o rótulo do tema (`- **Juros** · [Manchete](<link>) (fonte)`). No fim, uma nota em texto pequeno (`-# `) diz que as manchetes são **relacionadas, não a causa**. O texto nunca afirma causalidade.
   - Fonte e tema passam por `escapar` (Markdown do Discord). O título, dentro de `[...]`, passa por `escapar_texto_de_link`, que não escapa `( ) # -`: dentro do texto de um link, o Discord mostraria a barra ("Bradesco \(BBDC4\)"). Só links `https`, com `)` e espaço codificados na URL.
   - Limite: **2000 caracteres por mensagem, contando as URLs** (os links do Google News têm até ~600 caracteres). `dividir_em_mensagens` junta blocos (parágrafo, cabeçalho, cada ativo, contexto, nota) até o limite. Bloco maior que o limite começa numa mensagem nova e é quebrado por linha, e linha maior que o limite é quebrada por palavra (`quebrar_linha`), **sem nunca cortar um link `[texto](url)` no meio**. Texto e destaques são divididos separadamente: os destaques sempre começam numa mensagem nova.

As manchetes vêm de `data/AAAA-MM-DD-news.json` (gerado às 7h30); se o arquivo não tiver o usuário (rodando local, por exemplo), `notify.py` busca na hora.

Falhas:
- Notícias ou RSS com problema: a edição segue sem manchetes.
- Card com problema: o texto é enviado mesmo assim.
- Erro do Discord com um usuário (DM bloqueada, id errado): os outros continuam.

No fim, o log mostra só contagens (`Usuários | enviados | já enviados | com texto do Claude | sem ações | sem card | edição do Claude: sim/não | falhas`) e os motivos das falhas, por exemplo `HTTP 403 ao enviar card: 50007 Cannot send messages to this user`. O script sai com código 1 se houver falha ou card ausente.

Prévia: `python notify.py --previa` gera cards e mostra as mensagens de todos, sem enviar nem gravar em `data/enviados/`.

No `envio.yml`, o navegador é instalado com `python -m playwright install --with-deps chromium` (o `coleta.yml` não precisa dele).

### Texto do Claude (módulo opcional)

Uma **tarefa agendada do Claude**, configurada fora do código, roda às 8h com as instruções de `prompts/narrativa.md`. O módulo é opcional: sem a tarefa, ou se ela falhar, o fallback das 9h envia card + destaques para todos.

- **Entrada:** só `data/<data>.json` e `data/<data>-news.json`. Se um deles não existir, a tarefa para sem escrever nada. **Não pesquisa na web.**
- **Saída `edicao/AAAA-MM-DD.md`:** reportagem curta, estilo jornal. `## Geral` (3 parágrafos) + `## <código>` (2 a 4 parágrafos, agrupando ativos por assunto) para cada usuário com `texto_claude: true` em `usuarios` do arquivo de notícias. Seções por código, nunca por nome. Links `[título](url)` copiados do arquivo de notícias.
- **Regras do texto:**
  - **sem preços, pontos nem variações** (estão no card, que vem antes); a direção (subiu/caiu) vem do sinal no JSON. Outros números só se estiverem no título de uma manchete linkada. Decidido em 28/10/2026, depois do teste: o texto conta a história, o card traz os números;
  - todo "porquê" tem link de uma manchete do arquivo, atribuído à notícia; sem manchete, "sem notícia específica";
  - fatos, sem opinião nem recomendação;
  - leitura de 2 a 3 minutos;
  - português do Brasil, sem travessões;
  - no máximo 2 links por parágrafo (limite do Discord).
- **Commit:** `git add -f edicao/<data>.md` (a pasta é ignorada no template) e push, na branch principal ou numa branch própria.
- `notify.py` lê as seções com `ler_edicao` (títulos `## `). A seção de um código só vai para o dono desse código, e só se `texto_claude` for `true`.
- **Para mudar o texto, edite `prompts/narrativa.md`**, não o código. Se o formato de saída mudar (títulos das seções), ajuste `ler_edicao` e `blocos_do_texto`.

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
- **Seleção dos ativos:** só ativos com `dado_do_pregao`. Altas são as variações > 0 e baixas as < 0; num dia sem nenhuma alta, não há ▲.
- **Janela de 24h:** às 7h30, cobre as notícias desde as 7h30 do dia anterior, incluindo o pregão e o pós-fechamento.
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
- **Saída:** `python news.py` (no `coleta.yml`, depois do `collect.py`) grava `data/AAAA-MM-DD-news.json`, sem os descartes:
  ```json
  {"data": "...", "pregao": "...",
   "contexto_geral": [{"titulo", "url", "fonte", "publicado", "tema"}],
   "usuarios": {"<código>": {"texto_claude": true, "tickers": [...],
                             "movimentos": [{"ticker", "var_dia_pct", "busca_ok", "noticias": [...]}],
                             "contexto": [...]}}}
  ```
  `contexto_geral` usa só os motores de `temas.yml` (base da seção "Geral" do texto do Claude). A tarefa do Claude e o envio leem este mesmo arquivo, então as manchetes do texto e dos destaques são as mesmas. `buscar_noticias` ainda devolve `descartes` para diagnóstico em memória.

## Contrato do JSON de saída

O agente de narrativa depende deste formato. Mudanças aqui precisam ser intencionais. O JSON do dia tem **todos** os tickers da união dos usuários; o recorte por usuário é feito só na hora do envio.

```json
{
  "data": "2026-10-29",
  "pregao": "2026-10-28",
  "coletado_em": "2026-10-29T07:30:12-03:00",
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

- `data`: dia da edição (e do nome do arquivo).
- `pregao`: data do pregão de referência = data da cotação do Ibovespa (ou a mais recente entre os ativos, se o Ibovespa falhar). Às 7h30 é o pregão anterior.

`<ativo>`: `ticker`, `nome`, `preco`, `var_dia_pct` (variação no pregão de referência), `var_semana_pct` (vs. último fechamento da semana anterior), `var_mes_pct` (vs. último fechamento do mês anterior), `horario_cotacao`, `dado_do_pregao` (bool: a cotação é do `pregao`).

**Mudança de 28/10/2026, com a coleta passando para 7h30:** `dado_de_hoje` virou `dado_do_pregao` e entrou `pregao`. Às 7h30 a bolsa ainda não abriu, então a regra antiga, baseada em "hoje", marcaria toda edição como `sem_pregao`.

Cada erro começa por `<origem>:`, que é o ticker ou o nome da série macro. O recorte por usuário usa esse prefixo.

Regras de `status`:
- `sem_pregao`: o `pregao` é anterior ao último dia útil antes de hoje (`dia_util_anterior`, só seg-sex), ou seja, houve feriado. Na segunda, o pregão de sexta é o esperado: `ok`.
- `parcial`: há erros ou algum ativo sem `dado_do_pregao`.
- `ok`: o resto.

Variações de semana e mês seguem o **padrão de calendário da imprensa** (desde 28/10/2026; antes eram 5 e 21 pregões):
- semana: preço atual vs. último fechamento do histórico **antes da segunda-feira** da semana da cotação (normalmente a sexta anterior);
- mês: preço atual vs. último fechamento **antes do dia 1º** do mês da cotação (último pregão do mês anterior).

A referência é a data da cotação (`horario_cotacao`), não o relógio: às 7h30, é o pregão anterior. Como só entram pontos anteriores à segunda-feira ou ao dia 1º, não importa se o histórico já traz o pregão do dia. O histórico de 3 meses cobre os dois casos.

## GitHub Actions

Os dois workflows começam pelo job `visibilidade` (`gh api repos/$GITHUB_REPOSITORY --jq .private`). O resto só roda se o resultado for `true`.

**`coleta.yml`**: dias úteis às 7h30 BRT (`30 10 * * 1-5`) e `workflow_dispatch`.
1. Python 3.12, sem Chromium.
2. `comandos.py` (`continue-on-error`).
3. `collect.py`.
4. `news.py` (`continue-on-error`: sem manchetes, o envio ainda manda o card).
5. `git add -f data/*.json estado/preferencias.json`, commit e push. **Não envia nada.**

**`envio.yml`**: dispara em três casos, no grupo de execução `envio` (nunca dois ao mesmo tempo):
- **push em `edicao/**` em qualquer branch:** lê `edicao/<hoje>.md` do commit que recebeu o push (`git show $GITHUB_SHA:...`). **Só envia se a edição de hoje estiver nesse commit**; senão, espera o fallback. Pushes feitos com o `GITHUB_TOKEN` não disparam workflows; os da tarefa do Claude, com credencial própria, disparam.
- **9h BRT (`0 12 * * 1-5`), o fallback:** procura `edicao/<hoje>.md` em todas as branches, da mais recente para a mais antiga. Se achar, envia com texto; se não, envia card + destaques.
- **`workflow_dispatch`:** igual ao fallback.

Em todos os casos, o código, `data/` e `data/enviados/` vêm da branch principal (`checkout` com `ref` = branch padrão). Depois do `notify.py`, o passo "Registrar os envios" roda com `if: always()`: commita `data/enviados/`, faz `pull --rebase` e push. Quem já recebeu nunca recebe de novo, mesmo se a tarefa do Claude atrasar além das 9h.

**Horários:** o agendamento do GitHub pode atrasar de 5 a 30 minutos. Se a coleta das 7h30 atrasar além das 8h, a tarefa do Claude não acha os arquivos e para, e o fallback das 9h envia sem texto. Se isso for comum, agende a tarefa para 8h15 ou 8h30.

Secrets do repo privado: `BRAPI_TOKEN`, `DISCORD_BOT_TOKEN`, `USUARIOS_YAML` (o conteúdo inteiro do YAML). A tarefa do Claude precisa de permissão de push no repo privado (fora do código).

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
5. [ ] GitHub Actions: `coleta.yml` (7h30) e `envio.yml` (push/9h) escritos; falta cadastrar os Secrets no repo privado e acompanhar a primeira execução
6. [ ] Texto do Claude: `prompts/narrativa.md` e o envio prontos; falta configurar a tarefa agendada das 8h (fora do código) com permissão de push
7. [ ] README do template (repo privado próprio ou entrar como usuário no prod; `usuarios.example.yml`)

Evoluções depois da v1: juros futuros (DI) como termômetro de risco, variação no ano com os JSONs acumulados, edição semanal.
