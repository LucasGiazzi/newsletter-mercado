"""Busca manchetes relacionadas no Google News (RSS em pt-BR, últimas 24h).

Para as 2 maiores altas e as 2 maiores baixas do dia (do JSON mais recente) e para o
contexto geral ("Ibovespa"). São notícias relacionadas ao ativo, não a causa do movimento.
Saída em out/noticias-AAAA-MM-DD.json, que o notify.py reaproveita com --noticias.
Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import json
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from card import carregar_ultimo_json

RAIZ = Path(__file__).resolve().parent
PASTA_SAIDA = RAIZ / "out"

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

# Sufixos que só atrapalham a busca: "Itau Unibanco Holding SA Pfd" -> "Itau Unibanco"
SUFIXOS_NOME = re.compile(r"(?<!\w)(S\.A\.|S/A|SA|Pfd|ON|PN|Holding)(?!\w)")
# Manchetes com tom de recomendação ficam de fora: o projeto é só informativo
TERMOS_RECOMENDACAO = re.compile(
    r"recomend|\bcomprar\b|\bvender\b|vale a pena|pre[cç]o[- ]alvo|potencial de valoriza", re.IGNORECASE
)
# Páginas de cotação não são notícia: "BBDC4 - Banco Bradesco - Resultados, Dividendos, Cotação..."
PAGINAS_DE_COTACAO = re.compile(r"^[A-Z]{4}\d{1,2}\s*[-–]|cota[cç][aã]o hoje|dividendos, cota[cç][aã]o", re.IGNORECASE)


# ---------- busca ----------

def nome_para_busca(nome):
    """'B3 SA - Brasil, Bolsa, Balcao' -> 'B3'; 'Banco do Brasil S.A.' -> 'Banco do Brasil'."""
    nome = SUFIXOS_NOME.sub(" ", nome.split(" - ")[0])
    return " ".join(nome.replace(",", " ").split())


def data_publicacao(texto):
    try:
        return parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        return None


def ler_item(item, limite):
    """Converte um <item> do RSS em manchete; None se faltar dado ou for antiga."""
    titulo = (item.findtext("title") or "").strip()
    url = (item.findtext("link") or "").strip()
    fonte = (item.findtext("source") or "").strip()
    if fonte and titulo.endswith(f" - {fonte}"):
        titulo = titulo[: -len(fonte) - 3]
    publicado = data_publicacao(item.findtext("pubDate"))
    if not titulo or not url.startswith("https://") or publicado is None or publicado < limite:
        return None
    return {"titulo": titulo, "url": url, "fonte": fonte, "publicado": publicado.isoformat()}


def buscar_rss(consulta):
    """Manchetes das últimas 24h para a consulta; None se a busca falhar."""
    params = {"q": f"{consulta} when:1d", **PARAMS_IDIOMA}
    try:
        resposta = requests.get(RSS_URL, params=params, headers=CABECALHOS, timeout=TIMEOUT)
        resposta.raise_for_status()
        raiz = ET.fromstring(resposta.content)
    except (requests.RequestException, ET.ParseError) as erro:
        print(f"  RSS '{consulta}': {type(erro).__name__}", file=sys.stderr)
        return None
    limite = datetime.now(timezone.utc) - JANELA
    return [m for m in (ler_item(i, limite) for i in raiz.iterfind("./channel/item")) if m]


def normalizar(texto):
    """Minúsculas, sem acentos e espaços repetidos: 'Itaú  Unibanco' -> 'itau unibanco'."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def citam_primeiro(manchetes, ativo, nome_busca):
    """Manchetes que citam ticker ou nome no título vêm antes (ordem do Google mantida no resto)."""
    termos = [normalizar(ativo["ticker"]), normalizar(nome_busca)]
    return sorted(manchetes or [], key=lambda m: not any(t in normalizar(m["titulo"]) for t in termos))


def escolher(manchetes, vistos, quantidade):
    """Até 'quantidade' manchetes inéditas na mensagem, sem tom de recomendação e que sejam notícia."""
    escolhidas = []
    for manchete in manchetes or []:
        titulo = manchete["titulo"]
        chave = normalizar(titulo)
        if chave in vistos or manchete["url"] in vistos:
            continue
        if TERMOS_RECOMENDACAO.search(titulo) or PAGINAS_DE_COTACAO.search(titulo):
            continue
        vistos.update({chave, manchete["url"]})
        escolhidas.append(manchete)
        if len(escolhidas) == quantidade:
            break
    return escolhidas


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
    return {"data": dia["data"], "movimentos": movimentos, "contexto": []}


def buscar_noticias(dia):
    vistos = set()
    movimentos = []
    for ativo in maiores_movimentos(dia["ativos"]):
        nome_busca = nome_para_busca(ativo["nome"])
        manchetes = buscar_rss(f"{nome_busca} {ativo['ticker']}")
        escolhidas = escolher(citam_primeiro(manchetes, ativo, nome_busca), vistos, MANCHETES_POR_ATIVO)
        movimentos.append(movimento(ativo, escolhidas, manchetes is not None))
        time.sleep(PAUSA_ENTRE_BUSCAS)
    contexto = escolher(buscar_rss(BUSCA_CONTEXTO), vistos, MANCHETES_CONTEXTO)
    return {"data": dia["data"], "movimentos": movimentos, "contexto": contexto}


# ---------- saída ----------

def salvar_noticias(noticias):
    PASTA_SAIDA.mkdir(exist_ok=True)
    caminho = PASTA_SAIDA / f"noticias-{noticias['data']}.json"
    caminho.write_text(json.dumps(noticias, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return caminho


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    noticias = buscar_noticias(carregar_ultimo_json())
    for mov in noticias["movimentos"]:
        print(f"{mov['ticker']}: {len(mov['noticias'])} manchete(s)")
    print(f"Contexto: {len(noticias['contexto'])} manchete(s)")
    print(f"Notícias salvas: {salvar_noticias(noticias)}")


if __name__ == "__main__":
    main()
