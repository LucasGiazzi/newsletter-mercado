"""Envia a edição do dia por DM no Discord, uma por usuário: card em imagem + texto com destaques e notícias.

Para cada usuário (usuarios.py): card só com os tickers dele (card.py), destaques entre os ativos
dele e "Contexto do mercado" com os temas dele (news.py), enviados por DM ao discord_id dele.
Falha em um usuário não impede os outros. Logs só com contagens (privacidade).

    python notify.py --previa                    gera tudo e mostra as mensagens, sem enviar
    python notify.py --reusar-noticias           envia reaproveitando out/noticias-AAAA-MM-DD-<código>.json

Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

from card import PASTA_SAIDA, carregar_ultimo_json, data_br, gerar_card, numero, pct
from news import buscar_noticias, noticias_vazias, salvar_noticias
from usuarios import carregar_usuarios, todos_os_tickers

RAIZ = Path(__file__).resolve().parent

DISCORD_API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com, 1.0)"  # formato exigido pelo Discord
TIMEOUT = 30
MAX_TENTATIVAS = 3
LIMITE_DISCORD = 2000  # caracteres por mensagem, contando as URLs dos links
SUPRIMIR_PREVIAS = 1 << 2  # flag SUPPRESS_EMBEDS: sem prévia dos links
PAUSA_ENTRE_MENSAGENS = 0.5


class ErroDiscord(Exception):
    """Falha da API do Discord; a mensagem nunca contém token nem ids."""


# ---------- recorte por usuário ----------

def filtrar_para_usuario(dia, usuario, todos):
    """Cópia do JSON só com os ativos do usuário; erros de tickers de outros usuários não aparecem."""
    meus = set(usuario["tickers"])

    def erro_visivel(erro):
        origem = erro.split(":")[0]
        return origem in meus or origem not in todos  # macro e índices valem para todos

    ativos = [a for a in dia["ativos"] if a["ticker"] in meus]
    erros = [e for e in dia["erros"] if erro_visivel(e)]
    if dia["status"] == "sem_pregao":
        status = "sem_pregao"
    elif erros or any(not a["dado_de_hoje"] for a in ativos):
        status = "parcial"
    else:
        status = "ok"
    return {**dia, "ativos": ativos, "erros": erros, "status": status}


def codigo_do_usuario(usuario):
    """Código curto e estável para nomear arquivos em out/ sem expor o discord_id.

    Não usar a posição na lista: se ela mudar entre a prévia e o envio, um usuário
    receberia as notícias (e os tickers) de outro.
    """
    return hashlib.sha256(usuario["discord_id"].encode()).hexdigest()[:10]


# ---------- notícias ----------

def obter_noticias(dia, temas, sufixo, reusar):
    """Reaproveita o arquivo da prévia ou busca agora. Falha nunca impede o envio."""
    caminho = PASTA_SAIDA / f"noticias-{dia['data']}{sufixo}.json"
    try:
        if reusar and caminho.exists():
            noticias = json.loads(caminho.read_text(encoding="utf-8"))
            meus = {a["ticker"] for a in dia["ativos"]}
            if noticias.get("data") != dia["data"]:
                raise ValueError("arquivo de outra data")
            if any(m["ticker"] not in meus for m in noticias["movimentos"]):
                raise ValueError("arquivo com ativos de outro usuário")
            return noticias
        noticias = buscar_noticias(dia, temas)
        salvar_noticias(noticias, sufixo)
        return noticias
    except Exception as erro:  # RSS, arquivo ou formato: segue sem manchetes
        print(f"  notícias indisponíveis para um usuário ({type(erro).__name__})", file=sys.stderr)
        return noticias_vazias(dia)


# ---------- texto (Markdown do Discord) ----------

def escapar(texto):
    """Escapa o Markdown do Discord em títulos, fontes e temas vindos de fora."""
    return re.sub(r"([\\*_~`|>\[\]()#-])", r"\\\1", texto)


def linha_manchete(manchete):
    url = manchete["url"].replace(")", "%29").replace(" ", "%20")
    tema = f"**{escapar(manchete['tema'])}** · " if manchete.get("tema") else ""
    fonte = f" ({escapar(manchete['fonte'])})" if manchete.get("fonte") else ""
    return f"- {tema}[{escapar(manchete['titulo'])}](<{url}>){fonte}"


def bloco_movimento(mov):
    seta = "▲" if mov["var_dia_pct"] > 0 else "▼"
    linhas = [f"{seta} **{escapar(mov['ticker'])}** {pct(mov['var_dia_pct'])}%"]
    if mov["noticias"]:
        linhas += [linha_manchete(m) for m in mov["noticias"]]
    else:
        linhas.append("*sem notícia específica*" if mov["busca_ok"] else "*notícias indisponíveis*")
    return "\n".join(linhas)


def montar_blocos(dia, noticias):
    """Blocos do texto, na ordem: cabeçalho, ativos, contexto, nota."""
    cabecalho = [f"**Destaques · {data_br(dia['data'])}**"]
    if dia["status"] == "sem_pregao":
        cabecalho.append("Sem pregão hoje; o card mostra o último pregão disponível.")
    elif dia["status"] == "parcial":
        cabecalho.append(f"Coleta parcial: {len(dia['erros'])} erro(s), listados no card.")
    for indice in dia["indices"]:
        cabecalho.append(
            f"{escapar(indice['nome'].title())} {pct(indice['var_dia_pct'])}% no dia, aos {numero(indice['preco'], 0)} pts."
        )

    blocos = ["\n".join(cabecalho)]
    blocos += [bloco_movimento(mov) for mov in noticias["movimentos"]]
    if noticias["contexto"]:
        blocos.append("**Contexto do mercado**\n" + "\n".join(linha_manchete(m) for m in noticias["contexto"]))
    blocos.append(
        "-# Manchetes relacionadas das últimas 24h (Google News); não indicam a causa dos movimentos. "
        "Informativo; não é recomendação de investimento."
    )
    return blocos


def dividir_em_mensagens(blocos):
    """Junta blocos em mensagens de até 2000 caracteres. Bloco grande demais começa numa mensagem
    nova e é quebrado por linha, para o título da seção não ficar sozinho no fim da anterior."""
    mensagens, atual = [], ""

    def adicionar(pedaco, separador):
        nonlocal atual
        if atual and len(atual) + len(separador) + len(pedaco) <= LIMITE_DISCORD:
            atual += separador + pedaco
        else:
            if atual:
                mensagens.append(atual)
            atual = pedaco[:LIMITE_DISCORD]

    for bloco in blocos:
        if len(bloco) <= LIMITE_DISCORD:
            adicionar(bloco, "\n\n")
            continue
        if atual:
            mensagens.append(atual)
            atual = ""
        for linha in bloco.split("\n"):
            adicionar(linha, "\n")
    if atual:
        mensagens.append(atual)
    return mensagens


# ---------- envio ----------

def criar_sessao_discord(token):
    sessao = requests.Session()
    sessao.headers.update({"Authorization": f"Bot {token}", "User-Agent": USER_AGENT})
    return sessao


def descrever_resposta(resposta, acao):
    """'HTTP 403 ao enviar mensagem: 50007 Cannot send messages to this user' (sem ids)."""
    try:
        corpo = resposta.json()
        detalhe = f"{corpo.get('code', '')} {corpo.get('message', '')}".strip()
    except ValueError:
        detalhe = ""
    return f"HTTP {resposta.status_code} ao {acao}: {detalhe}"


def chamar_discord(sessao, acao, caminho, **kwargs):
    """POST na API do Discord, respeitando o retry_after do 429. Erros sem token nem ids."""
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            resposta = sessao.post(f"{DISCORD_API}{caminho}", timeout=TIMEOUT, **kwargs)
        except requests.RequestException as erro:
            raise ErroDiscord(f"falha de conexão ao {acao} ({type(erro).__name__})") from None
        if resposta.status_code == 429 and tentativa < MAX_TENTATIVAS:
            try:
                espera = float(resposta.json().get("retry_after", 1))
            except ValueError:
                espera = 1.0
            time.sleep(espera + 0.2)
            continue
        if resposta.status_code >= 400:
            raise ErroDiscord(descrever_resposta(resposta, acao))
        return resposta.json() if resposta.content else {}
    raise ErroDiscord(f"limite de requisições ao {acao}")


def abrir_dm(sessao, discord_id):
    """Canal de DM entre o bot e o usuário (o Discord devolve o mesmo canal se já existir)."""
    return chamar_discord(sessao, "abrir DM", "/users/@me/channels", json={"recipient_id": discord_id})["id"]


def enviar_mensagem(sessao, canal, texto, imagem=None, nome_imagem=None):
    """Mensagem sem prévia de links e sem menções; com imagem, vai como anexo."""
    dados = {"content": texto, "flags": SUPRIMIR_PREVIAS, "allowed_mentions": {"parse": []}}
    caminho = f"/channels/{canal}/messages"
    if imagem is None:
        chamar_discord(sessao, "enviar mensagem", caminho, json=dados)
    else:
        dados["attachments"] = [{"id": 0, "filename": nome_imagem}]
        arquivos = {"files[0]": (nome_imagem, imagem.read_bytes(), "image/png")}  # bytes: reenviável no 429
        chamar_discord(sessao, "enviar card", caminho, data={"payload_json": json.dumps(dados)}, files=arquivos)
    time.sleep(PAUSA_ENTRE_MENSAGENS)


def enviar_edicao(sessao, usuario, dia, card, mensagens):
    canal = abrir_dm(sessao, usuario["discord_id"])
    if card:
        enviar_mensagem(sessao, canal, f"**Mercado B3 · {data_br(dia['data'])}**", card, f"mercado-{dia['data']}.png")
    for texto in mensagens:
        enviar_mensagem(sessao, canal, texto)


# ---------- principal ----------

def preparar_edicao(dia_usuario, usuario, sufixo, reusar):
    """Card e mensagens de um usuário. Sem card (falha do Playwright), devolve None no lugar do caminho."""
    try:
        card = gerar_card(dia_usuario, sufixo)
    except Exception as erro:  # qualquer falha do Playwright: o texto ainda é enviado
        print(f"  card indisponível para um usuário ({type(erro).__name__})", file=sys.stderr)
        card = None
    noticias = obter_noticias(dia_usuario, usuario["temas"], sufixo, reusar)
    return card, dividir_em_mensagens(montar_blocos(dia_usuario, noticias))


def descrever_falha(erro):
    """Motivo da falha para o log, sem dados do usuário."""
    return str(erro) if isinstance(erro, ErroDiscord) else type(erro).__name__


def ler_argumentos():
    parser = argparse.ArgumentParser(description="Envia a edição do dia por DM no Discord, uma por usuário.")
    parser.add_argument("--previa", action="store_true", help="gera cards e notícias e mostra as mensagens, sem enviar")
    parser.add_argument("--reusar-noticias", action="store_true", help="reaproveita as notícias salvas pela prévia")
    return parser.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    args = ler_argumentos()
    load_dotenv(RAIZ / ".env")
    dia = carregar_ultimo_json()
    usuarios = carregar_usuarios()
    todos = todos_os_tickers(usuarios)

    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    enviar = not args.previa and bool(token)
    if not args.previa and not token:
        print("DISCORD_BOT_TOKEN não definido: nada será enviado.", file=sys.stderr)
    sessao = criar_sessao_discord(token) if enviar else None

    enviados, sem_card, falhas = 0, 0, Counter()
    for posicao, usuario in enumerate(usuarios, 1):
        try:
            dia_usuario = filtrar_para_usuario(dia, usuario, todos)
            sufixo = f"-{codigo_do_usuario(usuario)}"
            card, mensagens = preparar_edicao(dia_usuario, usuario, sufixo, args.reusar_noticias)
            sem_card += card is None
            if enviar:
                enviar_edicao(sessao, usuario, dia_usuario, card, mensagens)
                enviados += 1
            else:  # prévia local: aqui o conteúdo aparece, porque é para o dono conferir
                print(f"\n=== Prévia {posicao}/{len(usuarios)} · card: {card} ===")
                for i, texto in enumerate(mensagens, 1):
                    print(f"--- mensagem {i}/{len(mensagens)} ({len(texto)} caracteres) ---\n{texto}")
        except Exception as erro:  # um usuário com problema não impede os outros
            falhas[descrever_falha(erro)] += 1

    print(f"Usuários: {len(usuarios)} | enviados: {enviados} | falhas: {sum(falhas.values())} | sem card: {sem_card}")
    for motivo, total in falhas.items():
        print(f"  falha: {motivo} x{total}")
    if falhas or sem_card:
        sys.exit(1)


if __name__ == "__main__":
    main()
