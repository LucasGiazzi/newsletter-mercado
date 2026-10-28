"""Envia a edição do dia ao Telegram, uma por usuário: card em imagem + texto com destaques e notícias.

Para cada usuário (usuarios.py): card só com os tickers dele (card.py), destaques entre os ativos
dele e "Contexto do mercado" com os temas dele (news.py), enviados ao chat_id dele.
Falha em um usuário não impede os outros. Logs só com contagens (privacidade).

    python notify.py --previa                    gera tudo e mostra os textos, sem enviar
    python notify.py --reusar-noticias           envia reaproveitando out/noticias-AAAA-MM-DD-N.json

Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import argparse
import copy
import html
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

from card import PASTA_SAIDA, carregar_ultimo_json, data_br, gerar_card, numero, pct
from news import buscar_noticias, noticias_vazias, salvar_noticias
from usuarios import carregar_usuarios, todos_os_tickers

RAIZ = Path(__file__).resolve().parent

TELEGRAM_API = "https://api.telegram.org/bot{token}/{metodo}"
TIMEOUT = 30
LIMITE_TELEGRAM = 4096  # caracteres visíveis, depois de interpretar o HTML


class ErroTelegram(Exception):
    """Falha da Bot API; a mensagem nunca contém URL (token) nem chat_id."""


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


# ---------- notícias ----------

def obter_noticias(dia, temas, sufixo, reusar):
    """Reaproveita o arquivo da prévia ou busca agora. Falha nunca impede o envio."""
    caminho = PASTA_SAIDA / f"noticias-{dia['data']}{sufixo}.json"
    try:
        if reusar and caminho.exists():
            noticias = json.loads(caminho.read_text(encoding="utf-8"))
            if noticias.get("data") != dia["data"]:
                raise ValueError("arquivo de outra data")
            return noticias
        noticias = buscar_noticias(dia, temas)
        salvar_noticias(noticias, sufixo)
        return noticias
    except Exception as erro:  # RSS, arquivo ou formato: segue sem manchetes
        print(f"  notícias indisponíveis para um usuário ({type(erro).__name__})", file=sys.stderr)
        return noticias_vazias(dia)


# ---------- texto ----------

def linha_manchete(manchete):
    link = f'<a href="{html.escape(manchete["url"], quote=True)}">{html.escape(manchete["titulo"])}</a>'
    return link + (f" ({html.escape(manchete['fonte'])})" if manchete.get("fonte") else "")


def bloco_movimento(mov):
    seta = "▲" if mov["var_dia_pct"] > 0 else "▼"
    linhas = [f"{seta} <b>{html.escape(mov['ticker'])}</b> {pct(mov['var_dia_pct'])}%"]
    if mov["noticias"]:
        linhas += [f"  • {linha_manchete(m)}" for m in mov["noticias"]]
    else:
        linhas.append("  <i>sem notícia específica</i>" if mov["busca_ok"] else "  <i>notícias indisponíveis</i>")
    return "\n".join(linhas)


def montar_texto(dia, noticias):
    cabecalho = [f"<b>Destaques · {data_br(dia['data'])}</b>"]
    if dia["status"] == "sem_pregao":
        cabecalho.append("Sem pregão hoje; o card mostra o último pregão disponível.")
    elif dia["status"] == "parcial":
        cabecalho.append(f"Coleta parcial: {len(dia['erros'])} erro(s), listados no card.")
    for indice in dia["indices"]:
        cabecalho.append(
            f"{html.escape(indice['nome'].title())} {pct(indice['var_dia_pct'])}% no dia, aos {numero(indice['preco'], 0)} pts."
        )

    partes = ["\n".join(cabecalho)]
    partes += [bloco_movimento(mov) for mov in noticias["movimentos"]]
    if noticias["contexto"]:
        partes.append("<b>Contexto do mercado</b>\n" + "\n".join(f"• {linha_manchete(m)}" for m in noticias["contexto"]))
    partes.append(
        "<i>Manchetes relacionadas das últimas 24h (Google News); não indicam a causa dos movimentos.\n"
        "Informativo; não é recomendação de investimento.</i>"
    )
    return "\n\n".join(partes)


def tamanho_visivel(texto_html):
    """O Telegram conta o limite depois de interpretar o HTML: tags não contam."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", texto_html)))


def remover_ultima_manchete(noticias):
    """Tira a manchete de menor prioridade: contexto primeiro, depois do último ativo."""
    if noticias["contexto"]:
        noticias["contexto"].pop()
        return True
    for mov in reversed(noticias["movimentos"]):
        if mov["noticias"]:
            mov["noticias"].pop()
            return True
    return False


def montar_texto_no_limite(dia, noticias):
    noticias = copy.deepcopy(noticias)
    texto = montar_texto(dia, noticias)
    while tamanho_visivel(texto) > LIMITE_TELEGRAM and remover_ultima_manchete(noticias):
        texto = montar_texto(dia, noticias)
    return texto


# ---------- envio ----------

def chamar_telegram(token, metodo, **kwargs):
    """POST na Bot API. Os erros nunca mostram a URL, porque ela contém o token."""
    try:
        resposta = requests.post(TELEGRAM_API.format(token=token, metodo=metodo), timeout=TIMEOUT, **kwargs)
    except requests.RequestException as erro:
        raise ErroTelegram(f"falha de conexão em {metodo} ({type(erro).__name__})") from None
    if resposta.status_code != 200:
        try:
            descricao = resposta.json().get("description", "")
        except ValueError:
            descricao = ""
        raise ErroTelegram(f"HTTP {resposta.status_code} em {metodo}: {descricao}")


def enviar_card(token, chat_id, caminho, legenda):
    with caminho.open("rb") as imagem:
        chamar_telegram(token, "sendPhoto", data={"chat_id": chat_id, "caption": legenda}, files={"photo": imagem})


def enviar_texto(token, chat_id, texto):
    dados = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    chamar_telegram(token, "sendMessage", json=dados)


# ---------- principal ----------

def preparar_edicao(dia_usuario, usuario, sufixo, reusar):
    """Card e texto de um usuário. Sem card (falha do Playwright), devolve None no lugar do caminho."""
    try:
        card = gerar_card(dia_usuario, sufixo)
    except Exception as erro:  # qualquer falha do Playwright: o texto ainda é enviado
        print(f"  card indisponível para um usuário ({type(erro).__name__})", file=sys.stderr)
        card = None
    noticias = obter_noticias(dia_usuario, usuario["temas"], sufixo, reusar)
    return card, montar_texto_no_limite(dia_usuario, noticias)


def descrever_falha(erro):
    """Motivo da falha para o log, sem dados do usuário."""
    return str(erro) if isinstance(erro, ErroTelegram) else type(erro).__name__


def ler_argumentos():
    parser = argparse.ArgumentParser(description="Envia a edição do dia ao Telegram, uma por usuário.")
    parser.add_argument("--previa", action="store_true", help="gera cards e notícias e mostra os textos, sem enviar")
    parser.add_argument("--reusar-noticias", action="store_true", help="reaproveita as notícias salvas pela prévia")
    return parser.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    args = ler_argumentos()
    load_dotenv(RAIZ / ".env")
    dia = carregar_ultimo_json()
    usuarios = carregar_usuarios()
    todos = todos_os_tickers(usuarios)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    enviar = not args.previa and bool(token)
    if not args.previa and not token:
        print("TELEGRAM_BOT_TOKEN não definido: nada será enviado.", file=sys.stderr)

    enviados, sem_card, falhas = 0, 0, Counter()
    for posicao, usuario in enumerate(usuarios, 1):
        try:
            dia_usuario = filtrar_para_usuario(dia, usuario, todos)
            card, texto = preparar_edicao(dia_usuario, usuario, f"-{posicao}", args.reusar_noticias)
            sem_card += card is None
            if enviar:
                if card:
                    enviar_card(token, usuario["chat_id"], card, f"Mercado B3 · {data_br(dia['data'])}")
                enviar_texto(token, usuario["chat_id"], texto)
                enviados += 1
            else:  # prévia local: aqui o conteúdo aparece, porque é para o dono conferir
                print(f"\n=== Prévia {posicao}/{len(usuarios)} · card: {card} ===\n{texto}")
        except Exception as erro:  # um usuário com problema não impede os outros
            falhas[descrever_falha(erro)] += 1

    print(f"Usuários: {len(usuarios)} | enviados: {enviados} | falhas: {sum(falhas.values())} | sem card: {sem_card}")
    for motivo, total in falhas.items():
        print(f"  falha: {motivo} x{total}")
    if falhas or sem_card:
        sys.exit(1)


if __name__ == "__main__":
    main()
