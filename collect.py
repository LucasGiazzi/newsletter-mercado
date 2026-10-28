"""Coleta diária de cotações da B3 (brapi) e indicadores do Banco Central (SGS).

Grava data/AAAA-MM-DD.json no formato descrito no CLAUDE.md.
Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
ARQUIVO_TICKERS = RAIZ / "tickers.txt"
PASTA_DADOS = RAIZ / "data"

BRAPI_BASE = "https://brapi.dev/api/v2/stocks"
SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/1?formato=json"

# Brasil sem horário de verão desde 2019: UTC-3 fixo evita depender do pacote tzdata no Windows
FUSO_BRT = timezone(timedelta(hours=-3))

INDICES = ["^BVSP"]
SERIES_SGS = {
    "selic_meta": 432,
    "ipca_mensal": 433,
    "dolar_ptax_venda": 1,
}

PAUSA_ENTRE_CHAMADAS = 1.5  # plano gratuito: 1 requisição simultânea
MAX_TENTATIVAS = 3
TIMEOUT = 20
TIMEOUT_SGS = 30
PAUSA_SGS = 3
PREGOES_SEMANA = 5
PREGOES_MES = 21


class ErroColeta(Exception):
    """Falha ao obter um dado; a mensagem vai para a lista de erros do JSON."""


# ---------- entrada ----------

def ler_tickers():
    """Lê tickers.txt ignorando linhas vazias e comentários (#)."""
    tickers = []
    for linha in ARQUIVO_TICKERS.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#"):
            tickers.append(linha.upper())
    return tickers


def criar_sessao_brapi():
    """Sessão HTTP com o token no header (o token nunca é impresso)."""
    sessao = requests.Session()
    token = os.environ.get("BRAPI_TOKEN", "").strip()
    if token:
        sessao.headers["Authorization"] = f"Bearer {token}"
    else:
        print("Aviso: BRAPI_TOKEN não definido; só tickers públicos vão responder.", file=sys.stderr)
    return sessao


# ---------- brapi ----------

_ultima_chamada = 0.0


def esperar_vez():
    """Garante a pausa mínima entre chamadas à brapi."""
    global _ultima_chamada
    espera = PAUSA_ENTRE_CHAMADAS - (time.monotonic() - _ultima_chamada)
    if espera > 0:
        time.sleep(espera)
    _ultima_chamada = time.monotonic()


def mensagem_http(resposta):
    """Monta uma mensagem curta de erro a partir da resposta da brapi."""
    descricoes = {401: "token inválido", 403: "fora do plano", 404: "não encontrado", 429: "limite de requisições"}
    detalhe = ""
    try:
        detalhe = resposta.json().get("message", "")
    except ValueError:
        pass
    partes = [f"HTTP {resposta.status_code}", descricoes.get(resposta.status_code, ""), detalhe]
    return " - ".join(p for p in partes if p)


def chamar_brapi(sessao, endpoint, params):
    """GET na brapi v2 com pausa entre chamadas e respeito ao Retry-After no 429."""
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        esperar_vez()
        try:
            resposta = sessao.get(f"{BRAPI_BASE}/{endpoint}", params=params, timeout=TIMEOUT)
        except requests.RequestException as erro:
            raise ErroColeta(f"falha de conexão em /{endpoint}: {type(erro).__name__}") from erro

        if resposta.status_code == 429 and tentativa < MAX_TENTATIVAS:
            espera = resposta.headers.get("Retry-After", "")
            time.sleep(int(espera) if espera.isdigit() else 10)
            continue
        if resposta.status_code != 200:
            raise ErroColeta(f"/{endpoint}: {mensagem_http(resposta)}")
        return resposta.json()
    raise ErroColeta(f"/{endpoint}: limite de requisições após {MAX_TENTATIVAS} tentativas")


def primeiro_resultado(corpo, endpoint):
    """Extrai results[0].data, que é onde a brapi v2 coloca os dados."""
    resultados = corpo.get("results") or []
    if not resultados or not resultados[0].get("data"):
        raise ErroColeta(f"/{endpoint}: resposta sem dados")
    return resultados[0]["data"]


def buscar_cotacao(sessao, ticker):
    corpo = chamar_brapi(sessao, "quote", {"symbols": ticker})
    return primeiro_resultado(corpo, "quote")


def buscar_historico(sessao, ticker):
    """Lista de (data, fechamento) em ordem crescente."""
    params = {"symbols": ticker, "range": "3mo", "interval": "1d", "sortOrder": "asc"}
    corpo = chamar_brapi(sessao, "historical", params)
    pontos = primeiro_resultado(corpo, "historical").get("historicalDataPrice") or []
    historico = [(converter_data(p["date"]), p["close"]) for p in pontos if p.get("close") is not None]
    return sorted(historico)


# ---------- datas e cálculos ----------

def converter_data(valor):
    """Converte o 'date' da brapi (unix em segundos ou ISO) para data em BRT."""
    if isinstance(valor, (int, float)):
        return datetime.fromtimestamp(valor, FUSO_BRT).date()
    return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).astimezone(FUSO_BRT).date()


def converter_horario(iso_utc):
    """'2026-10-28T21:30:30.000Z' -> datetime em BRT."""
    return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(FUSO_BRT)


def variacao_pct(atual, anterior):
    if not anterior:
        return None
    return round((atual / anterior - 1) * 100, 2)


def fechamento_n_pregoes_antes(historico, data_ref, n):
    """Fechamento n pregões antes de data_ref, usando só pontos anteriores a ela."""
    anteriores = [fechamento for data, fechamento in historico if data < data_ref]
    if len(anteriores) < n:
        return None
    return anteriores[-n]


def montar_ativo(sessao, ticker, hoje):
    """Junta cotação e histórico no formato <ativo> do contrato."""
    cotacao = buscar_cotacao(sessao, ticker)
    preco = cotacao.get("regularMarketPrice")
    horario_txt = cotacao.get("regularMarketTime")
    if preco is None or not horario_txt:
        raise ErroColeta("/quote: sem preço ou horário")
    horario = converter_horario(horario_txt)

    historico = buscar_historico(sessao, ticker)
    # Referência é a data da cotação: em dia útil é hoje; em feriado, o último pregão
    data_ref = horario.date()
    var_dia = cotacao.get("regularMarketChangePercent")

    return {
        "ticker": ticker,
        "nome": cotacao.get("longName") or cotacao.get("shortName") or ticker,
        "preco": preco,
        "var_dia_pct": round(var_dia, 2) if var_dia is not None else None,
        "var_semana_pct": variacao_pct(preco, fechamento_n_pregoes_antes(historico, data_ref, PREGOES_SEMANA)),
        "var_mes_pct": variacao_pct(preco, fechamento_n_pregoes_antes(historico, data_ref, PREGOES_MES)),
        "horario_cotacao": horario.isoformat(),
        "dado_de_hoje": horario.date() == hoje,
    }


def coletar_ativos(sessao, tickers, hoje, erros):
    """Coleta cada ticker; falha em um não interrompe os demais."""
    ativos = []
    for ticker in tickers:
        try:
            ativos.append(montar_ativo(sessao, ticker, hoje))
            print(f"  {ticker}: ok")
        except (ErroColeta, KeyError, TypeError, ValueError) as erro:
            erros.append(f"{ticker}: {erro}")
            print(f"  {ticker}: ERRO {erro}")
    return ativos


# ---------- Banco Central ----------

def buscar_serie_sgs(codigo):
    """Último valor de uma série do SGS: {'data': 'dd/mm/aaaa', 'valor': float}.

    O SGS é lento e devolve 502 de vez em quando, por isso tenta algumas vezes.
    """
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            resposta = requests.get(SGS_URL.format(codigo=codigo), timeout=TIMEOUT_SGS)
            resposta.raise_for_status()
            ultimo = resposta.json()[-1]
            return {"data": ultimo["data"], "valor": float(ultimo["valor"])}
        except (requests.RequestException, ValueError, KeyError, IndexError) as erro:
            if tentativa == MAX_TENTATIVAS:
                raise ErroColeta(f"SGS {codigo}: {type(erro).__name__} após {MAX_TENTATIVAS} tentativas") from erro
            time.sleep(PAUSA_SGS)


def coletar_macro(erros):
    macro = {}
    for nome, codigo in SERIES_SGS.items():
        try:
            macro[nome] = buscar_serie_sgs(codigo)
        except ErroColeta as erro:
            macro[nome] = {"data": None, "valor": None}
            erros.append(f"{nome}: {erro}")
    return macro


# ---------- saída ----------

def definir_status(indices, ativos, erros):
    ibov = next((i for i in indices if i["ticker"] == "^BVSP"), None)
    if ibov is not None and not ibov["dado_de_hoje"]:
        return "sem_pregao"
    if erros or any(not a["dado_de_hoje"] for a in ativos):
        return "parcial"
    return "ok"


def gravar_json(resultado, hoje):
    PASTA_DADOS.mkdir(exist_ok=True)
    caminho = PASTA_DADOS / f"{hoje.isoformat()}.json"
    caminho.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return caminho


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    load_dotenv(RAIZ / ".env")
    agora = datetime.now(FUSO_BRT)
    hoje = agora.date()
    erros = []

    sessao = criar_sessao_brapi()
    print("Índices:")
    indices = coletar_ativos(sessao, INDICES, hoje, erros)
    print("Ativos:")
    ativos = coletar_ativos(sessao, ler_tickers(), hoje, erros)
    print("Macro (Banco Central)...")
    macro = coletar_macro(erros)

    resultado = {
        "data": hoje.isoformat(),
        "coletado_em": agora.replace(microsecond=0).isoformat(),
        "status": definir_status(indices, ativos, erros),
        "indices": indices,
        "ativos": ativos,
        "macro": macro,
        "erros": erros,
    }
    caminho = gravar_json(resultado, hoje)
    print(f"Status: {resultado['status']} | erros: {len(erros)} | arquivo: {caminho.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
