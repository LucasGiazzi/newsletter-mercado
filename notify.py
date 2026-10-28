"""Envia a edição do dia ao Telegram: card em imagem + texto com destaques e notícias.

O card (card.py) traz os números do JSON mais recente de data/. O texto traz as 2 maiores
altas e baixas com manchetes relacionadas (news.py) e o contexto do mercado.

    python notify.py --previa                     gera card e notícias, só mostra o texto
    python notify.py --noticias out/noticias-AAAA-MM-DD.json   envia reaproveitando as notícias

Sem TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID, funciona como --previa.
Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import argparse
import copy
import html
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from card import carregar_ultimo_json, data_br, gerar_card, numero, pct
from news import buscar_noticias, noticias_vazias, salvar_noticias

RAIZ = Path(__file__).resolve().parent

TELEGRAM_API = "https://api.telegram.org/bot{token}/{metodo}"
TIMEOUT = 30
LIMITE_TELEGRAM = 4096  # caracteres visíveis, depois de interpretar o HTML


# ---------- notícias ----------

def obter_noticias(dia, caminho):
    """Lê o arquivo de --noticias ou busca agora. Falha nunca impede o envio."""
    try:
        if caminho:
            noticias = json.loads(Path(caminho).read_text(encoding="utf-8"))
            if noticias.get("data") != dia["data"]:
                raise ValueError(f"arquivo é de {noticias.get('data')}, o JSON é de {dia['data']}")
            return noticias
        noticias = buscar_noticias(dia)
        print(f"Notícias salvas: {salvar_noticias(noticias)}")
        return noticias
    except Exception as erro:  # RSS, arquivo ou formato: segue sem manchetes
        print(f"Falha nas notícias: {type(erro).__name__}: {erro}", file=sys.stderr)
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
        raise SystemExit(f"Falha de conexão com o Telegram ({metodo}): {type(erro).__name__}") from None
    if resposta.status_code != 200:
        try:
            descricao = resposta.json().get("description", "")
        except ValueError:
            descricao = ""
        raise SystemExit(f"Telegram respondeu HTTP {resposta.status_code} em {metodo}: {descricao}")


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

def ler_argumentos():
    parser = argparse.ArgumentParser(description="Envia a edição do dia ao Telegram.")
    parser.add_argument("--previa", action="store_true", help="gera card e notícias e mostra o texto, sem enviar")
    parser.add_argument("--noticias", help="reaproveita um out/noticias-AAAA-MM-DD.json em vez de buscar de novo")
    return parser.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    args = ler_argumentos()
    load_dotenv(RAIZ / ".env")
    dia = carregar_ultimo_json()

    try:
        card = gerar_card(dia)
        print(f"Card gerado: {card}")
    except Exception as erro:  # qualquer falha do Playwright: o texto ainda é enviado
        card = None
        print(f"Falha ao gerar o card: {type(erro).__name__}: {erro}", file=sys.stderr)

    texto = montar_texto_no_limite(dia, obter_noticias(dia, args.noticias))
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if args.previa or not (token and chat_id):
        print(f"--- texto ({tamanho_visivel(texto)} caracteres visíveis) ---")
        print(texto)
        if not args.previa:
            print("\n(TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não definidos: nada enviado)", file=sys.stderr)
    else:
        if card:
            enviar_card(token, chat_id, card, f"Mercado B3 · {data_br(dia['data'])}")
        enviar_texto(token, chat_id, texto)
        print("Edição enviada ao Telegram.")

    if card is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
