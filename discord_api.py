"""Chamadas à API REST do Discord como bot: abrir DM, enviar e ler mensagens.

Só usa requests. Os erros nunca mostram token, ids nem URLs (privacidade).
"""

import json
import time

import requests

DISCORD_API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com, 1.0)"  # formato exigido pelo Discord
TIMEOUT = 30
MAX_TENTATIVAS = 3
SUPRIMIR_PREVIAS = 1 << 2  # flag SUPPRESS_EMBEDS: sem prévia dos links
PAUSA_ENTRE_MENSAGENS = 0.5
MENSAGENS_POR_PAGINA = 100


class ErroDiscord(Exception):
    """Falha da API do Discord; a mensagem nunca contém token nem ids."""


def criar_sessao(token):
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


def chamar(sessao, metodo, acao, caminho, **kwargs):
    """Chamada à API respeitando o retry_after do 429. Erros sem token nem ids."""
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            resposta = sessao.request(metodo, f"{DISCORD_API}{caminho}", timeout=TIMEOUT, **kwargs)
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
    return chamar(sessao, "POST", "abrir DM", "/users/@me/channels", json={"recipient_id": discord_id})["id"]


def enviar_mensagem(sessao, canal, texto, imagem=None, nome_imagem=None):
    """Mensagem sem prévia de links e sem menções; com imagem, vai como anexo."""
    dados = {"content": texto, "flags": SUPRIMIR_PREVIAS, "allowed_mentions": {"parse": []}}
    caminho = f"/channels/{canal}/messages"
    if imagem is None:
        chamar(sessao, "POST", "enviar mensagem", caminho, json=dados)
    else:
        dados["attachments"] = [{"id": 0, "filename": nome_imagem}]
        arquivos = {"files[0]": (nome_imagem, imagem.read_bytes(), "image/png")}  # bytes: reenviável no 429
        chamar(sessao, "POST", "enviar card", caminho, data={"payload_json": json.dumps(dados)}, files=arquivos)
    time.sleep(PAUSA_ENTRE_MENSAGENS)


def ler_mensagens(sessao, canal, depois_de="0"):
    """Mensagens do canal com id maior que 'depois_de', da mais antiga para a mais nova.

    Em DMs com o bot, o conteúdo vem sem precisar do intent de Message Content.
    """
    mensagens = []
    while True:
        params = {"after": depois_de, "limit": MENSAGENS_POR_PAGINA}
        lote = chamar(sessao, "GET", "ler mensagens", f"/channels/{canal}/messages", params=params)
        if not lote:
            break
        lote.sort(key=lambda m: int(m["id"]))
        mensagens += lote
        depois_de = lote[-1]["id"]
        if len(lote) < MENSAGENS_POR_PAGINA:
            break
    return mensagens
