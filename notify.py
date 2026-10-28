"""Envia a edição do dia ao Telegram: card em imagem + texto com destaques e notícias.

O card (card.py) traz os números do JSON mais recente de data/. O texto traz destaques
automáticos do JSON e, opcionalmente, destaques e notícias da camada de narrativa:

    python notify.py --noticias arquivo.json
    {"destaques": ["texto", ...], "noticias": [{"titulo": "...", "url": "https://...", "fonte": "..."}]}

Sem TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (ou com --previa), gera o card e só mostra o texto.
Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import argparse
import html
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from card import carregar_ultimo_json, data_br, gerar_card, numero, pct

RAIZ = Path(__file__).resolve().parent

TELEGRAM_API = "https://api.telegram.org/bot{token}/{metodo}"
TIMEOUT = 30


# ---------- texto ----------

def destaques_automaticos(dia):
    """Destaques tirados só dos números do JSON."""
    destaques = []
    if dia["status"] == "sem_pregao":
        destaques.append("Sem pregão hoje; o card mostra o último pregão disponível.")
    elif dia["status"] == "parcial":
        destaques.append(f"Coleta parcial: {len(dia['erros'])} erro(s), listados no card.")

    for indice in dia["indices"]:
        destaques.append(f"{indice['nome'].title()} {pct(indice['var_dia_pct'])}% no dia, aos {numero(indice['preco'], 0)} pts.")

    com_variacao = [a for a in dia["ativos"] if a["var_dia_pct"] is not None]
    if com_variacao:
        maior = max(com_variacao, key=lambda a: a["var_dia_pct"])
        menor = min(com_variacao, key=lambda a: a["var_dia_pct"])
        destaques.append(f"Maior variação do dia: {maior['ticker']} {pct(maior['var_dia_pct'])}%.")
        destaques.append(f"Menor variação do dia: {menor['ticker']} {pct(menor['var_dia_pct'])}%.")
    return [html.escape(d) for d in destaques]


def carregar_narrativa(caminho):
    """Lê destaques e notícias da camada de narrativa; links só http(s)."""
    if not caminho:
        return [], []
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    destaques = [html.escape(str(d)) for d in dados.get("destaques", [])]
    noticias = []
    for item in dados.get("noticias", []):
        url = str(item.get("url", ""))
        if not url.startswith(("https://", "http://")):
            continue
        linha = f'<a href="{html.escape(url, quote=True)}">{html.escape(str(item.get("titulo", url)))}</a>'
        if item.get("fonte"):
            linha += f" ({html.escape(str(item['fonte']))})"
        noticias.append(linha)
    return destaques, noticias


def montar_texto(dia, destaques_narrativa, noticias):
    partes = [f"<b>Destaques · {data_br(dia['data'])}</b>\n" + "\n".join(
        f"• {d}" for d in destaques_automaticos(dia) + destaques_narrativa
    )]
    if noticias:
        partes.append("<b>Notícias</b>\n" + "\n".join(f"• {n}" for n in noticias))
    partes.append("<i>Informativo; não é recomendação de investimento.</i>")
    return "\n\n".join(partes)


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
    parser.add_argument("--previa", action="store_true", help="gera o card e mostra o texto, sem enviar")
    parser.add_argument("--noticias", help="JSON com destaques e notícias da camada de narrativa")
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

    texto = montar_texto(dia, *carregar_narrativa(args.noticias))
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if args.previa or not (token and chat_id):
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
