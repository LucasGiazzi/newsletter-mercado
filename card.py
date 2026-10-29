"""Gera o card em imagem (PNG) com os números do JSON mais recente de data/.

Template Jinja2 em templates/card.html; screenshot com Playwright (Chromium).
Saída em out/card-AAAA-MM-DD.png (e o .html usado, para conferência).
Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent
PASTA_DADOS = RAIZ / "data"
PASTA_TEMPLATES = RAIZ / "templates"
PASTA_SAIDA = RAIZ / "out"

LARGURA = 1080
ESCALA = 2  # device_scale_factor: imagem final com 2160 px de largura
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
# Brasil sem horário de verão desde 2019: UTC-3 fixo evita depender do pacote tzdata no Windows
FUSO_BRT = timezone(timedelta(hours=-3))


# ---------- entrada ----------
# Convenção: arquivos de data/ e edicao/ são nomeados pela data do PREGÃO, não pela data em
# que a coleta ou o envio rodaram. Subpastas (data/testes/, data/enviados/) ficam de fora.

def data_de_hoje():
    """'AAAA-MM-DD' de hoje em Brasília."""
    return datetime.now(FUSO_BRT).date().isoformat()


def carregar_pregao_mais_recente():
    """JSON do pregão mais recente em data/ (o nome AAAA-MM-DD é a data do pregão)."""
    arquivos = sorted(PASTA_DADOS.glob("????-??-??.json"))
    if not arquivos:
        raise SystemExit("Nenhuma coleta em data/; rode collect.py antes.")
    return json.loads(arquivos[-1].read_text(encoding="utf-8"))


def ja_enviado(pregao):
    """True se a edição desse pregão já foi enviada (data/enviados/<pregão>.json existe)."""
    return (PASTA_DADOS / "enviados" / f"{pregao}.json").exists()


def aviso(titulo, texto):
    """Aviso que não pode passar em silêncio: no GitHub Actions vira anotação no resumo da execução."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::notice title={titulo}::{texto}")
    else:
        print(f"{titulo}: {texto}")


# ---------- formatação (também usada pelo notify.py) ----------

def numero(valor, casas=2):
    """1234.5 -> '1.234,50' (padrão brasileiro)."""
    if valor is None:
        return "—"
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(valor, casas=2):
    """Variação com sinal sempre visível: 2.25 -> '+2,25', -1.5 -> '−1,50'."""
    if valor is None:
        return "—"
    sinal = "+" if valor > 0 else "−" if valor < 0 else ""
    return sinal + numero(abs(valor), casas)


def variacao(valor):
    """Variação com '%' para o card; sem valor, só o travessão."""
    return "—" if valor is None else pct(valor) + "%"


def classe(valor):
    """Classe CSS da variação: verde/vermelho só aqui."""
    if not valor:
        return "neutro"
    return "alta" if valor > 0 else "queda"


def mes_ref(data_br):
    """'01/09/2026' -> 'set/2026' (mês de referência do IPCA)."""
    if not data_br:
        return "—"
    _, mes, ano = data_br.split("/")
    return f"{MESES[int(mes) - 1]}/{ano}"


def data_br(iso):
    """'2026-10-28' -> '28/10/2026'."""
    return "/".join(reversed(iso.split("-")))


# ---------- card ----------

def ordenar_por_dia(ativos):
    """Maior variação do dia primeiro; sem variação vai para o fim."""
    return sorted(ativos, key=lambda a: (a["var_dia_pct"] is None, -(a["var_dia_pct"] or 0)))


def renderizar_html(dia):
    ambiente = Environment(loader=FileSystemLoader(PASTA_TEMPLATES), autoescape=select_autoescape(["html"]))
    ambiente.filters.update(numero=numero, variacao=variacao, classe=classe, mes_ref=mes_ref)
    coletado = datetime.fromisoformat(dia["coletado_em"])
    return ambiente.get_template("card.html").render(
        dia=dia,
        ativos=ordenar_por_dia(dia["ativos"]),
        data_br=data_br(dia.get("pregao") or dia["data"]),  # o card mostra o pregão, não a data da edição
        coletado_br=coletado.strftime("%d/%m/%Y %H:%M"),
    )


def fotografar(html, destino):
    """Screenshot só do card, na altura que o conteúdo ocupar."""
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page(viewport={"width": LARGURA, "height": 800}, device_scale_factor=ESCALA)
        pagina.set_content(html, wait_until="load")
        pagina.locator("#card").screenshot(path=str(destino))
        navegador.close()


def gerar_card(dia, sufixo=""):
    """Gera out/card-<pregão>{sufixo}.png e devolve o caminho (sufixo: código do usuário)."""
    PASTA_SAIDA.mkdir(exist_ok=True)
    html = renderizar_html(dia)
    (PASTA_SAIDA / f"card-{dia.get('pregao') or dia['data']}{sufixo}.html").write_text(html, encoding="utf-8")
    destino = PASTA_SAIDA / f"card-{dia.get('pregao') or dia['data']}{sufixo}.png"
    fotografar(html, destino)
    return destino


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    print(f"Card gerado: {gerar_card(carregar_pregao_mais_recente())}")


if __name__ == "__main__":
    main()
