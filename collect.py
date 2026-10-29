"""Coleta diária de cotações da B3 (brapi) e indicadores do Banco Central (SGS).

Busca uma vez cada ticker da união dos usuários (usuarios.py) e grava data/AAAA-MM-DD.json
no formato descrito no CLAUDE.md. Logs só com contagens, nunca tickers (privacidade).
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

from usuarios import carregar_usuarios, todos_os_tickers

RAIZ = Path(__file__).resolve().parent
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
CABECALHOS_SGS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json",
}


class ErroColeta(Exception):
    """Falha ao obter um dado; a mensagem vai para a lista de erros do JSON."""


# ---------- entrada ----------

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


def ultimo_fechamento_antes(historico, limite):
    """Último fechamento com data anterior a 'limite'; None se o histórico não alcança."""
    anteriores = [fechamento for data, fechamento in historico if data < limite]
    return anteriores[-1] if anteriores else None


def montar_ativo(sessao, ticker):
    """Junta cotação e histórico no formato <ativo> do contrato (dado_do_pregao entra depois)."""
    cotacao = buscar_cotacao(sessao, ticker)
    preco = cotacao.get("regularMarketPrice")
    horario_txt = cotacao.get("regularMarketTime")
    if preco is None or not horario_txt:
        raise ErroColeta("/quote: sem preço ou horário")
    horario = converter_horario(horario_txt)

    historico = buscar_historico(sessao, ticker)
    # Referência é a data da cotação (o pregão), não o relógio: às 7h30, é o pregão anterior
    data_ref = horario.date()
    # Padrão de calendário da imprensa: vs. último fechamento da semana e do mês anteriores
    fim_semana_anterior = ultimo_fechamento_antes(historico, data_ref - timedelta(days=data_ref.weekday()))
    fim_mes_anterior = ultimo_fechamento_antes(historico, data_ref.replace(day=1))
    var_dia = cotacao.get("regularMarketChangePercent")

    return {
        "ticker": ticker,
        "nome": cotacao.get("longName") or cotacao.get("shortName") or ticker,
        "preco": preco,
        "var_dia_pct": round(var_dia, 2) if var_dia is not None else None,
        "var_semana_pct": variacao_pct(preco, fim_semana_anterior),
        "var_mes_pct": variacao_pct(preco, fim_mes_anterior),
        "horario_cotacao": horario.isoformat(),
    }


def coletar_ativos(sessao, tickers, erros):
    """Coleta cada ticker; falha em um não interrompe os demais. O detalhe vai só para o JSON."""
    ativos = []
    for ticker in tickers:
        try:
            ativos.append(montar_ativo(sessao, ticker))
        except (ErroColeta, KeyError, TypeError, ValueError) as erro:
            erros.append(f"{ticker}: {erro}")
    return ativos


# ---------- Banco Central ----------

def ler_resposta_sgs(resposta):
    """Último ponto da série. Quando não é o JSON esperado, o erro diz o que veio (para diagnóstico)."""
    tipo = resposta.headers.get("content-type", "?").split(";")[0]
    if resposta.status_code != 200:
        raise ErroColeta(f"HTTP {resposta.status_code} ({tipo})")
    try:
        dados = resposta.json()
    except ValueError:
        raise ErroColeta(f"resposta não é JSON (HTTP 200, {tipo})") from None
    try:
        ultimo = dados[-1]
        return {"data": ultimo["data"], "valor": float(ultimo["valor"])}
    except (KeyError, IndexError, TypeError, ValueError):
        raise ErroColeta(f"JSON sem data/valor (HTTP 200, {tipo})") from None


def buscar_serie_sgs(codigo):
    """Último valor de uma série do SGS: {'data': 'dd/mm/aaaa', 'valor': float}.

    O SGS é lento e devolve 502 de vez em quando, por isso tenta algumas vezes. Do GitHub
    Actions (fora do Brasil) já respondeu página HTML no lugar do JSON: daí os cabeçalhos de navegador.
    """
    motivo = ""
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            resposta = requests.get(SGS_URL.format(codigo=codigo), headers=CABECALHOS_SGS, timeout=TIMEOUT_SGS)
            return ler_resposta_sgs(resposta)
        except requests.RequestException as erro:
            motivo = type(erro).__name__
        except ErroColeta as erro:
            motivo = str(erro)
        if tentativa < MAX_TENTATIVAS:
            time.sleep(PAUSA_SGS)
    raise ErroColeta(f"SGS {codigo}: {motivo} após {MAX_TENTATIVAS} tentativas")


def ultimo_valor_conhecido(nome, hoje):
    """Valor mais recente da série em coletas anteriores (data/AAAA-MM-DD.json), com a data original."""
    for caminho in sorted(PASTA_DADOS.glob("????-??-??.json"), reverse=True):
        if caminho.stem >= hoje.isoformat():
            continue
        try:
            serie = json.loads(caminho.read_text(encoding="utf-8")).get("macro", {}).get(nome) or {}
        except ValueError:
            continue
        if serie.get("valor") is not None:
            return {"data": serie["data"], "valor": serie["valor"], "repetido": True}
    return None


def coletar_macro(erros, hoje):
    """Selic, IPCA e PTAX. Se o SGS falhar, usa o último valor conhecido (Selic e IPCA mudam pouco)
    e registra o erro mesmo assim, para o status ficar "parcial"."""
    macro = {}
    for nome, codigo in SERIES_SGS.items():
        try:
            macro[nome] = buscar_serie_sgs(codigo)
        except ErroColeta as erro:
            anterior = ultimo_valor_conhecido(nome, hoje)
            macro[nome] = anterior or {"data": None, "valor": None}
            complemento = f"; usado o último valor conhecido ({anterior['data']})" if anterior else ""
            erros.append(f"{nome}: {erro}{complemento}")
    return macro


# ---------- saída ----------

def data_da_cotacao(ativo):
    return datetime.fromisoformat(ativo["horario_cotacao"]).date()


def definir_pregao(indices, ativos):
    """Pregão de referência: a data da cotação do Ibovespa (ou a mais recente, se ele falhar)."""
    ibov = next((i for i in indices if i["ticker"] == "^BVSP"), None)
    if ibov is not None:
        return data_da_cotacao(ibov)
    datas = [data_da_cotacao(a) for a in ativos]
    return max(datas) if datas else None


def dia_util_anterior(hoje):
    """Último dia de semana antes de hoje (feriados não entram: quem os revela é o Ibovespa)."""
    dia = hoje - timedelta(days=1)
    while dia.weekday() >= 5:
        dia -= timedelta(days=1)
    return dia


def definir_status(pregao, ativos, erros, hoje):
    """sem_pregao: o pregão de referência é anterior ao último dia útil (houve feriado).
    parcial: há erros ou ativo cuja cotação não é do pregão de referência. ok: o resto."""
    if pregao is not None and pregao < dia_util_anterior(hoje):
        return "sem_pregao"
    if erros or any(not a["dado_do_pregao"] for a in ativos):
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
    tickers = todos_os_tickers(carregar_usuarios())

    sessao = criar_sessao_brapi()
    indices = coletar_ativos(sessao, INDICES, erros)
    ativos = coletar_ativos(sessao, tickers, erros)
    macro = coletar_macro(erros, hoje)

    pregao = definir_pregao(indices, ativos)
    for ativo in indices + ativos:
        ativo["dado_do_pregao"] = data_da_cotacao(ativo) == pregao

    resultado = {
        "data": hoje.isoformat(),
        "pregao": pregao.isoformat() if pregao else None,
        "coletado_em": agora.replace(microsecond=0).isoformat(),
        "status": definir_status(pregao, ativos, erros, hoje),
        "indices": indices,
        "ativos": ativos,
        "macro": macro,
        "erros": erros,
    }
    caminho = gravar_json(resultado, hoje)
    print(
        f"Status: {resultado['status']} | ativos: {len(ativos)}/{len(tickers)} | índices: {len(indices)}/{len(INDICES)}"
        f" | erros: {len(erros)} | arquivo: {caminho.relative_to(RAIZ)}"
    )


if __name__ == "__main__":
    main()
