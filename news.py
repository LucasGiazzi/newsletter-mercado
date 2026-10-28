"""Busca manchetes relacionadas no Google News (RSS em pt-BR, últimas 24h).

Para as 2 maiores altas e as 2 maiores baixas do dia entre os ativos recebidos e para o
"Contexto do mercado" (temas do usuário, ou "Ibovespa"). São notícias relacionadas,
não a causa do movimento. Cada descarte fica registrado com o motivo.
Logs só com contagens, nunca consultas ou tickers (privacidade).
Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import json
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from card import carregar_ultimo_json

RAIZ = Path(__file__).resolve().parent
PASTA_SAIDA = RAIZ / "out"
ARQUIVO_FONTES = RAIZ / "fontes.txt"

RSS_URL = "https://news.google.com/rss/search"
PARAMS_IDIOMA = {"hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}
CABECALHOS = {"User-Agent": "Mozilla/5.0 (newsletter-mercado)"}
TIMEOUT = 20
PAUSA_ENTRE_BUSCAS = 1.0
JANELA = timedelta(hours=24)

ATIVOS_POR_LADO = 2
MANCHETES_POR_ATIVO = 2
MANCHETES_CONTEXTO = 3
BUSCA_CONTEXTO = "Ibovespa"
# "eleição" sozinha traz política em geral; com "mercado", vêm os efeitos no mercado
SUFIXO_BUSCA_TEMA = "mercado"

# Manchetes parecidas (mesmo fato): texto quase igual ou muitas palavras-chave em comum
SIMILARIDADE_TEXTO = 0.8
SIMILARIDADE_PALAVRAS = 0.5
MIN_PALAVRAS_COMUNS = 3
PALAVRAS_VAZIAS = {
    "com", "sem", "para", "pela", "pelo", "por", "que", "dos", "das", "nos", "nas", "uma", "como",
    "mais", "mas", "apos", "sobre", "veja", "hoje", "entre", "diz",
}

# Nome usado pela imprensa quando difere do longName da brapi (comparação ignora acentos)
APELIDOS = {
    "PETR3": ["Petrobras"],
    "PETR4": ["Petrobras"],
    "ITUB4": ["Itau"],
    "BBDC3": ["Bradesco"],
    "BBDC4": ["Bradesco"],
    "PRIO3": ["PetroRio"],
    "MGLU3": ["Magalu"],
}

# Sufixos que só atrapalham a busca: "Itau Unibanco Holding SA Pfd" -> "Itau Unibanco"
SUFIXOS_NOME = re.compile(r"(?<!\w)(S\.A\.|S/A|SA|Pfd|ON|PN|Holding)(?!\w)")
# Especulação: título que termina em "?" também conta (ver motivo_descarte)
TERMOS_ESPECULATIVOS = re.compile(r"pode disparar|vale a pena|\bcomprar\b|a[cç][oõ]es para", re.IGNORECASE)
# Tom de recomendação fica de fora: o projeto é só informativo
TERMOS_RECOMENDACAO = re.compile(r"recomend|\bvender\b|pre[cç]o[- ]alvo|potencial de valoriza", re.IGNORECASE)
# Páginas de cotação não são notícia: "BBDC4 - Banco Bradesco - Resultados, Dividendos, Cotação..."
PAGINAS_DE_COTACAO = re.compile(r"^[A-Z]{4}\d{1,2}\s*[-–]|cota[cç][aã]o hoje|dividendos, cota[cç][aã]o", re.IGNORECASE)

_cache_rss = {}  # consulta -> manchetes (ou None): usuários com o mesmo ativo não repetem a busca


# ---------- texto ----------

def sem_acento(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def normalizar(texto):
    """Minúsculas, sem acentos e espaços repetidos: 'Itaú  Unibanco' -> 'itau unibanco'."""
    return " ".join(sem_acento(texto).lower().split())


def nome_para_busca(nome):
    """'B3 SA - Brasil, Bolsa, Balcao' -> 'B3'; 'Banco do Brasil S.A.' -> 'Banco do Brasil'."""
    nome = SUFIXOS_NOME.sub(" ", nome.split(" - ")[0])
    return " ".join(nome.replace(",", " ").split())


def padrao_do_ativo(ticker, nome_busca):
    """Ticker (qualquer caixa) ou nome/apelido (caixa exata, para 'Vale' não casar com 'vale')."""
    nomes = [re.escape(sem_acento(n)) for n in [nome_busca, *APELIDOS.get(ticker, [])] if n]
    alternativas = [f"(?i:{re.escape(ticker)})", *nomes]
    return re.compile(rf"(?<!\w)(?:{'|'.join(alternativas)})(?!\w)")


def padrao_do_tema(tema):
    """Radical do tema, sem acento: 'eleição' casa com 'eleições', 'petróleo' com 'petroleira'."""
    radical = normalizar(tema)
    if len(radical) > 5:
        radical = radical[:-2]
    return re.compile(rf"(?<!\w){re.escape(radical)}", re.IGNORECASE)


def palavras_chave(titulo):
    """Radicais de 4 letras ('Vamos' e 'VAMO3' viram 'vamo') e números sem separador ('5,34' -> '534')."""
    chaves = set()
    for palavra in re.findall(r"\d+(?:[.,]\d+)*|\w+", normalizar(titulo)):
        if palavra[0].isdigit():
            numero = re.sub(r"[.,]", "", palavra)
            if len(numero) >= 2:
                chaves.add(numero)
        elif len(palavra) >= 3 and palavra not in PALAVRAS_VAZIAS:
            chaves.add(palavra[:4])
    return chaves


def parecidas(titulo_a, titulo_b):
    """True se os títulos parecem o mesmo fato com outras palavras."""
    if SequenceMatcher(None, normalizar(titulo_a), normalizar(titulo_b)).ratio() >= SIMILARIDADE_TEXTO:
        return True
    chaves_a, chaves_b = palavras_chave(titulo_a), palavras_chave(titulo_b)
    comuns = len(chaves_a & chaves_b)
    return comuns >= MIN_PALAVRAS_COMUNS and comuns / min(len(chaves_a), len(chaves_b)) >= SIMILARIDADE_PALAVRAS


# ---------- fontes ----------

def ler_fontes():
    """Fontes aceitas de fontes.txt; None (sem filtro) se o arquivo não existir."""
    if not ARQUIVO_FONTES.exists():
        return None
    linhas = ARQUIVO_FONTES.read_text(encoding="utf-8").splitlines()
    return [normalizar(l) for l in linhas if l.strip() and not l.strip().startswith("#")]


def fonte_aceita(fonte, fontes):
    return fontes is None or any(normalizar(fonte).startswith(f) for f in fontes)


# ---------- busca ----------

def data_publicacao(texto):
    try:
        return parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        return None


def ler_item(item):
    """Converte um <item> do RSS em manchete; None se faltar título ou link https."""
    titulo = (item.findtext("title") or "").strip()
    url = (item.findtext("link") or "").strip()
    fonte = (item.findtext("source") or "").strip()
    if fonte and titulo.endswith(f" - {fonte}"):
        titulo = titulo[: -len(fonte) - 3]
    if not titulo or not url.startswith("https://"):
        return None
    publicado = data_publicacao(item.findtext("pubDate"))
    return {"titulo": titulo, "url": url, "fonte": fonte, "publicado": publicado.isoformat() if publicado else None}


def buscar_rss(consulta):
    """Manchetes da consulta (o filtro de 24h é refeito em motivo_descarte); None se a busca falhar."""
    if consulta in _cache_rss:
        return _cache_rss[consulta]
    time.sleep(PAUSA_ENTRE_BUSCAS)
    params = {"q": f"{consulta} when:1d", **PARAMS_IDIOMA}
    try:
        resposta = requests.get(RSS_URL, params=params, headers=CABECALHOS, timeout=TIMEOUT)
        resposta.raise_for_status()
        raiz = ET.fromstring(resposta.content)
        manchetes = [m for m in (ler_item(i) for i in raiz.iterfind("./channel/item")) if m]
    except (requests.RequestException, ET.ParseError) as erro:
        print(f"  RSS: falha em uma busca ({type(erro).__name__})", file=sys.stderr)
        manchetes = None
    _cache_rss[consulta] = manchetes
    return manchetes


# ---------- seleção das manchetes ----------

def motivo_descarte(manchete, filtros, vistos, padrao=None):
    """Primeiro motivo para descartar a manchete; None se ela serve."""
    titulo = manchete["titulo"]
    if manchete["publicado"] is None:
        return "sem data"
    if datetime.fromisoformat(manchete["publicado"]) < filtros["limite"]:
        return "mais de 24h"
    if not fonte_aceita(manchete["fonte"], filtros["fontes"]):
        return "fonte fora da lista"
    if padrao and not padrao.search(sem_acento(titulo)):
        return "não cita o ativo ou tema no título"
    if PAGINAS_DE_COTACAO.search(titulo):
        return "página de cotação"
    if titulo.rstrip().endswith("?") or TERMOS_ESPECULATIVOS.search(titulo):
        return "especulativo"
    if TERMOS_RECOMENDACAO.search(titulo):
        return "tom de recomendação"
    if manchete["url"] in vistos["urls"] or any(parecidas(titulo, t) for t in vistos["titulos"]):
        return "repetida ou parecida"
    return None


def escolher(manchetes, quantidade, busca, filtros, vistos, descartes, padrao=None):
    """Até 'quantidade' manchetes válidas, na ordem do Google; registra cada descarte."""
    escolhidas = []
    for manchete in manchetes or []:
        if len(escolhidas) == quantidade:
            break
        motivo = motivo_descarte(manchete, filtros, vistos, padrao)
        if motivo:
            descartes.append({"busca": busca, "motivo": motivo, "titulo": manchete["titulo"], "fonte": manchete["fonte"]})
            continue
        vistos["titulos"].append(manchete["titulo"])
        vistos["urls"].add(manchete["url"])
        escolhidas.append(manchete)
    return escolhidas


def consultas_de_contexto(temas):
    """(consulta, quantidade, padrão) por tema, dividindo as 3 manchetes; sem temas, 'Ibovespa'."""
    if not temas:
        return [(BUSCA_CONTEXTO, MANCHETES_CONTEXTO, None)]
    temas = temas[:MANCHETES_CONTEXTO]
    base, resto = divmod(MANCHETES_CONTEXTO, len(temas))
    return [
        (f"{tema} {SUFIXO_BUSCA_TEMA}", base + (1 if i < resto else 0), padrao_do_tema(tema))
        for i, tema in enumerate(temas)
    ]


# ---------- seleção dos ativos ----------

def maiores_movimentos(ativos):
    """2 maiores altas e 2 maiores baixas do dia, só com cotação de hoje."""
    de_hoje = [a for a in ativos if a["dado_de_hoje"] and a["var_dia_pct"] is not None]
    altas = sorted((a for a in de_hoje if a["var_dia_pct"] > 0), key=lambda a: -a["var_dia_pct"])
    baixas = sorted((a for a in de_hoje if a["var_dia_pct"] < 0), key=lambda a: a["var_dia_pct"])
    return altas[:ATIVOS_POR_LADO] + baixas[:ATIVOS_POR_LADO]


def movimento(ativo, noticias, busca_ok):
    return {
        "ticker": ativo["ticker"],
        "var_dia_pct": ativo["var_dia_pct"],
        "busca_ok": busca_ok,
        "noticias": noticias,
    }


def noticias_vazias(dia):
    """Mesma estrutura, sem manchetes: usada quando a busca inteira falha."""
    movimentos = [movimento(a, [], False) for a in maiores_movimentos(dia["ativos"])]
    return {"data": dia["data"], "movimentos": movimentos, "contexto": [], "descartes": []}


def buscar_noticias(dia, temas=()):
    """Notícias para os ativos de 'dia' (já filtrado por usuário) e para os temas dele."""
    filtros = {"limite": datetime.now(timezone.utc) - JANELA, "fontes": ler_fontes()}
    vistos = {"titulos": [], "urls": set()}
    descartes, movimentos = [], []
    for ativo in maiores_movimentos(dia["ativos"]):
        nome_busca = nome_para_busca(ativo["nome"])
        busca = f"{nome_busca} {ativo['ticker']}"
        manchetes = buscar_rss(busca)
        padrao = padrao_do_ativo(ativo["ticker"], nome_busca)
        escolhidas = escolher(manchetes, MANCHETES_POR_ATIVO, busca, filtros, vistos, descartes, padrao)
        movimentos.append(movimento(ativo, escolhidas, manchetes is not None))
    contexto = []
    for busca, quantidade, padrao in consultas_de_contexto(temas):
        contexto += escolher(buscar_rss(busca), quantidade, busca, filtros, vistos, descartes, padrao)
    return {"data": dia["data"], "movimentos": movimentos, "contexto": contexto, "descartes": descartes}


# ---------- saída ----------

def salvar_noticias(noticias, sufixo=""):
    PASTA_SAIDA.mkdir(exist_ok=True)
    caminho = PASTA_SAIDA / f"noticias-{noticias['data']}{sufixo}.json"
    caminho.write_text(json.dumps(noticias, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return caminho


def main():
    """Diagnóstico: notícias para todos os ativos do JSON, sem temas. Só contagens no terminal."""
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    noticias = buscar_noticias(carregar_ultimo_json())
    aceitas = sum(len(m["noticias"]) for m in noticias["movimentos"])
    print(f"Ativos com destaque: {len(noticias['movimentos'])} | manchetes: {aceitas} | contexto: {len(noticias['contexto'])}")
    for motivo, total in Counter(d["motivo"] for d in noticias["descartes"]).most_common():
        print(f"  descarte: {motivo} x{total}")
    print(f"Detalhes em {salvar_noticias(noticias)}")


if __name__ == "__main__":
    main()
