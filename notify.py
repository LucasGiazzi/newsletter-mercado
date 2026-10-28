"""Envia o resumo do JSON mais recente de data/ para o Telegram.

Sem TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (ou com --previa), só mostra a mensagem no terminal.
Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import html
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
PASTA_DADOS = RAIZ / "data"

TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 20


# ---------- entrada ----------

def carregar_ultimo_json():
    """JSON mais recente de data/ (o nome AAAA-MM-DD já ordena por data)."""
    arquivos = sorted(PASTA_DADOS.glob("????-??-??.json"))
    if not arquivos:
        raise SystemExit("Nenhum JSON em data/; rode collect.py antes.")
    return json.loads(arquivos[-1].read_text(encoding="utf-8"))


# ---------- formatação ----------

def numero(valor, casas=2):
    """1234.5 -> '1.234,50' (padrão brasileiro)."""
    if valor is None:
        return "—"
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(valor, casas=2):
    """Variação com sinal: 2.25 -> '+2,25'."""
    if valor is None:
        return "—"
    return ("+" if valor > 0 else "") + numero(valor, casas)


def bloco_indice(indice):
    nome = html.escape(indice["nome"])
    return (
        f"<b>{nome}</b> {numero(indice['preco'], 0)} pts | dia {pct(indice['var_dia_pct'])}%\n"
        f"semana {pct(indice['var_semana_pct'])}% · mês {pct(indice['var_mes_pct'])}%"
    )


def tabela_ativos(ativos):
    """Tabela em fonte monoespaçada, estreita o bastante para o celular."""
    linhas = [f"{'Ativo':<7}{'Preço':>8}{'Dia%':>6}{'Sem%':>6}{'Mês%':>6}"]
    for ativo in ativos:
        ticker = ativo["ticker"] + ("" if ativo["dado_de_hoje"] else "*")
        linhas.append(
            f"{ticker:<7}{numero(ativo['preco']):>8}"
            f"{pct(ativo['var_dia_pct'], 1):>6}{pct(ativo['var_semana_pct'], 1):>6}{pct(ativo['var_mes_pct'], 1):>6}"
        )
    tabela = "<pre>" + html.escape("\n".join(linhas)) + "</pre>"
    if any(not a["dado_de_hoje"] for a in ativos):
        tabela += "\n* sem cotação de hoje"
    return tabela


def linha_macro(macro):
    selic = macro.get("selic_meta", {})
    ipca = macro.get("ipca_mensal", {})
    dolar = macro.get("dolar_ptax_venda", {})
    mes_ipca = f" ({ipca['data'][3:]})" if ipca.get("data") else ""
    return (
        f"Selic {numero(selic.get('valor'))}% · IPCA {numero(ipca.get('valor'))}%{mes_ipca}"
        f" · Dólar R$ {numero(dolar.get('valor'), 3)}"
    )


def montar_mensagem(dia):
    data_br = "/".join(reversed(dia["data"].split("-")))
    partes = [f"<b>Mercado B3 · {data_br}</b>"]
    if dia["status"] == "sem_pregao":
        partes.append("Sem pregão hoje; valores do último pregão.")
    elif dia["status"] == "parcial":
        partes.append("Coleta parcial: veja os erros no fim.")

    partes += [bloco_indice(i) for i in dia["indices"]]
    if dia["ativos"]:
        partes.append(tabela_ativos(dia["ativos"]))
    partes.append(linha_macro(dia["macro"]))
    if dia["erros"]:
        partes.append("<b>Erros</b>\n" + "\n".join(html.escape(e) for e in dia["erros"]))
    partes.append("<i>Informativo; não é recomendação de investimento.</i>")
    return "\n\n".join(partes)


# ---------- envio ----------

def enviar_telegram(token, chat_id, texto):
    """Envia a mensagem. Os erros nunca mostram a URL, porque ela contém o token."""
    dados = {"chat_id": chat_id, "text": texto, "parse_mode": "HTML"}
    try:
        resposta = requests.post(TELEGRAM_URL.format(token=token), json=dados, timeout=TIMEOUT)
    except requests.RequestException as erro:
        raise SystemExit(f"Falha de conexão com o Telegram: {type(erro).__name__}") from None
    if resposta.status_code != 200:
        try:
            descricao = resposta.json().get("description", "")
        except ValueError:
            descricao = ""
        raise SystemExit(f"Telegram respondeu HTTP {resposta.status_code}: {descricao}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    load_dotenv(RAIZ / ".env")
    texto = montar_mensagem(carregar_ultimo_json())

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if "--previa" in sys.argv or not (token and chat_id):
        print(texto)
        if "--previa" not in sys.argv:
            print("\n(TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não definidos: mensagem não enviada)", file=sys.stderr)
        return

    enviar_telegram(token, chat_id, texto)
    print("Resumo enviado ao Telegram.")


if __name__ == "__main__":
    main()
