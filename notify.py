"""Envia a edição do dia por DM no Discord, uma por usuário.

Para cada usuário (usuarios.py), nesta ordem:
  1. card com os números dos tickers dele (card.py);
  2. só para quem tem texto_claude: true e se edicao/AAAA-MM-DD.md existir, o texto do Claude
     ("Geral" + a seção do código dele);
  3. destaques com manchetes e "Contexto do mercado" (data/AAAA-MM-DD-news.json, de news.py).

Usa só a coleta DE HOJE (nunca reenvia um dia anterior). Quem já está em
data/enviados/AAAA-MM-DD.json não recebe de novo. Falha em um usuário não impede os outros.
Logs só com contagens (privacidade).

    python notify.py --previa      gera tudo e mostra as mensagens, sem enviar nem registrar

Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from card import FUSO_BRT, PASTA_DADOS, carregar_json_do_dia, data_br, data_de_hoje, gerar_card, numero, pct
from discord_api import ErroDiscord, abrir_dm, criar_sessao, enviar_mensagem
from news import buscar_noticias, ler_noticias_do_dia, noticias_vazias
from usuarios import carregar_usuarios, filtrar_para_usuario, todos_os_tickers

RAIZ = Path(__file__).resolve().parent
PASTA_EDICAO = RAIZ / "edicao"
PASTA_ENVIADOS = PASTA_DADOS / "enviados"

LIMITE_DISCORD = 2000  # caracteres por mensagem, contando as URLs dos links
SECAO_GERAL = "Geral"
# Um link markdown inteiro ou uma palavra: unidades que nunca são cortadas ao meio
UNIDADE_DE_TEXTO = re.compile(r"\[[^\]]*\]\([^)]*\)|\S+")


# ---------- registro de envios ----------

def ler_enviados(data):
    """{codigo: {"enviado_em", "com_texto"}} de data/enviados/AAAA-MM-DD.json."""
    caminho = PASTA_ENVIADOS / f"{data}.json"
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}


def salvar_enviados(data, enviados):
    PASTA_ENVIADOS.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(enviados, ensure_ascii=False, indent=2, sort_keys=True)
    (PASTA_ENVIADOS / f"{data}.json").write_text(texto + "\n", encoding="utf-8")


# ---------- notícias ----------

def noticias_do_usuario(noticias_do_dia, dia_usuario, usuario):
    """Manchetes do arquivo do dia; se ele não existir (rodando local), busca agora."""
    salvas = noticias_do_dia.get("usuarios", {}).get(usuario["codigo"])
    if salvas:
        return salvas
    try:
        return buscar_noticias(dia_usuario, usuario["temas"])
    except Exception as erro:  # RSS ou formato: segue sem manchetes
        print(f"  notícias indisponíveis para um usuário ({type(erro).__name__})", file=sys.stderr)
        return noticias_vazias(dia_usuario)


# ---------- texto do Claude (edicao/AAAA-MM-DD.md) ----------

def ler_edicao(data):
    """Seções do texto do dia: {"Geral": texto, "<codigo>": texto}. Vazio se não existir."""
    caminho = PASTA_EDICAO / f"{data}.md"
    if not caminho.exists():
        return {}
    secoes, atual = {}, None
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        titulo = re.match(r"^##\s+(.+?)\s*$", linha)
        if titulo:
            atual = titulo.group(1)
            secoes[atual] = []
        elif atual:
            secoes[atual].append(linha)
    return {nome: "\n".join(linhas).strip() for nome, linhas in secoes.items() if "\n".join(linhas).strip()}


def paragrafos(texto):
    return [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]


def blocos_do_texto(edicao, usuario):
    """Texto do Claude para o usuário: "Panorama do mercado" + "Suas ações". Vazio se não for o caso."""
    geral = edicao.get(SECAO_GERAL)
    if not usuario["texto_claude"] or not geral:
        return []
    blocos = []
    for titulo, texto in (("Panorama do mercado", geral), ("Suas ações", edicao.get(usuario["codigo"], ""))):
        partes = paragrafos(texto)
        if partes:
            blocos.append(f"### {titulo}\n{partes[0]}")  # título junto do 1º parágrafo
            blocos += partes[1:]
    return blocos


# ---------- destaques (Markdown do Discord) ----------

def escapar(texto):
    """Escapa o Markdown do Discord em títulos, fontes e temas vindos de fora."""
    return re.sub(r"([\\*_~`|>\[\]()#-])", r"\\\1", texto)


def escapar_texto_de_link(texto):
    """Dentro de [texto](url) o Discord mostra a barra antes de ( ) # -: escapa só o que quebra o link."""
    return re.sub(r"([\\*_~`|\[\]])", r"\\\1", texto)


def linha_manchete(manchete):
    url = manchete["url"].replace(")", "%29").replace(" ", "%20")
    tema = f"**{escapar(manchete['tema'])}** · " if manchete.get("tema") else ""
    fonte = f" ({escapar(manchete['fonte'])})" if manchete.get("fonte") else ""
    return f"- {tema}[{escapar_texto_de_link(manchete['titulo'])}](<{url}>){fonte}"


def bloco_movimento(mov):
    seta = "▲" if mov["var_dia_pct"] > 0 else "▼"
    linhas = [f"{seta} **{escapar(mov['ticker'])}** {pct(mov['var_dia_pct'])}%"]
    if mov["noticias"]:
        linhas += [linha_manchete(m) for m in mov["noticias"]]
    else:
        linhas.append("*sem notícia específica*" if mov["busca_ok"] else "*notícias indisponíveis*")
    return "\n".join(linhas)


def data_do_pregao(dia):
    return data_br(dia.get("pregao") or dia["data"])


def montar_blocos(dia, noticias):
    """Blocos dos destaques, na ordem: cabeçalho, ativos, contexto, nota."""
    cabecalho = [f"**Destaques · fechamento de {data_do_pregao(dia)}**"]
    if dia["status"] == "sem_pregao":
        cabecalho.append("Não houve pregão no último dia útil; o card mostra o último pregão disponível.")
    elif dia["status"] == "parcial":
        cabecalho.append(f"Coleta parcial: {len(dia['erros'])} erro(s), listados no card.")
    for indice in dia["indices"]:
        cabecalho.append(
            f"{escapar(indice['nome'].title())} {pct(indice['var_dia_pct'])}% no pregão, aos {numero(indice['preco'], 0)} pts."
        )

    blocos = ["\n".join(cabecalho)]
    blocos += [bloco_movimento(mov) for mov in noticias["movimentos"]]
    if noticias["contexto"]:
        blocos.append("**Contexto do mercado**\n" + "\n".join(linha_manchete(m) for m in noticias["contexto"]))
    blocos.append(
        "-# Manchetes relacionadas das últimas 24h (Google News); não indicam a causa dos movimentos. "
        "Informativo; não é recomendação de investimento."
    )
    return blocos


# ---------- divisão em mensagens ----------

def quebrar_linha(linha):
    """Linha maior que o limite vira pedaços, sem cortar um link [texto](url) no meio."""
    pedacos, atual = [], ""
    for unidade in UNIDADE_DE_TEXTO.findall(linha):
        candidato = f"{atual} {unidade}" if atual else unidade
        if len(candidato) <= LIMITE_DISCORD:
            atual = candidato
        else:
            if atual:
                pedacos.append(atual)
            atual = unidade[:LIMITE_DISCORD]
    if atual:
        pedacos.append(atual)
    return pedacos


def dividir_em_mensagens(blocos):
    """Junta blocos em mensagens de até 2000 caracteres. Bloco grande demais começa numa mensagem
    nova e é quebrado por linha (e linha grande, por palavra), sem deixar título sozinho."""
    mensagens, atual = [], ""

    def adicionar(pedaco, separador):
        nonlocal atual
        if atual and len(atual) + len(separador) + len(pedaco) <= LIMITE_DISCORD:
            atual += separador + pedaco
        else:
            if atual:
                mensagens.append(atual)
            atual = pedaco

    for bloco in blocos:
        if len(bloco) <= LIMITE_DISCORD:
            adicionar(bloco, "\n\n")
            continue
        if atual:
            mensagens.append(atual)
            atual = ""
        for linha in bloco.split("\n"):
            for pedaco in quebrar_linha(linha) if len(linha) > LIMITE_DISCORD else [linha]:
                adicionar(pedaco, "\n")
    if atual:
        mensagens.append(atual)
    return mensagens


# ---------- envio ----------

def enviar_edicao(sessao, usuario, dia, card, mensagens):
    canal = abrir_dm(sessao, usuario["discord_id"])
    if card:
        legenda = f"**Mercado B3 · fechamento de {data_do_pregao(dia)}**"
        enviar_mensagem(sessao, canal, legenda, card, f"mercado-{dia.get('pregao') or dia['data']}.png")
    for texto in mensagens:
        enviar_mensagem(sessao, canal, texto)


# ---------- principal ----------

def preparar_edicao(dia_usuario, usuario, noticias_do_dia, edicao):
    """Card e mensagens de um usuário. Sem card (falha do Playwright), devolve None no lugar do caminho."""
    try:
        card = gerar_card(dia_usuario, f"-{usuario['codigo']}")
    except Exception as erro:  # qualquer falha do Playwright: o texto ainda é enviado
        print(f"  card indisponível para um usuário ({type(erro).__name__})", file=sys.stderr)
        card = None
    texto = dividir_em_mensagens(blocos_do_texto(edicao, usuario))
    noticias = noticias_do_usuario(noticias_do_dia, dia_usuario, usuario)
    destaques = dividir_em_mensagens(montar_blocos(dia_usuario, noticias))
    return card, texto, destaques


def descrever_falha(erro):
    """Motivo da falha para o log, sem dados do usuário."""
    return str(erro) if isinstance(erro, ErroDiscord) else type(erro).__name__


def ler_argumentos():
    parser = argparse.ArgumentParser(description="Envia a edição do dia por DM no Discord, uma por usuário.")
    parser.add_argument("--previa", action="store_true", help="gera tudo e mostra as mensagens, sem enviar nem registrar")
    return parser.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    args = ler_argumentos()
    load_dotenv(RAIZ / ".env")
    hoje = data_de_hoje()
    dia = carregar_json_do_dia(hoje)
    usuarios = carregar_usuarios()
    todos = todos_os_tickers(usuarios)
    noticias_do_dia, edicao, enviados = ler_noticias_do_dia(hoje), ler_edicao(hoje), ler_enviados(hoje)

    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    enviar = not args.previa and bool(token)
    if not args.previa and not token:
        print("DISCORD_BOT_TOKEN não definido: nada será enviado.", file=sys.stderr)
    sessao = criar_sessao(token) if enviar else None

    contagem, falhas = Counter(), Counter()
    for posicao, usuario in enumerate(usuarios, 1):
        if not usuario["tickers"]:  # removeu tudo com /del: volta a receber depois de um /add
            contagem["sem ações"] += 1
            continue
        if enviar and usuario["codigo"] in enviados:  # nunca enviar duas vezes no mesmo dia
            contagem["já enviados"] += 1
            continue
        try:
            dia_usuario = filtrar_para_usuario(dia, usuario, todos)
            card, texto, destaques = preparar_edicao(dia_usuario, usuario, noticias_do_dia, edicao)
            contagem["sem card"] += card is None
            if enviar:
                enviar_edicao(sessao, usuario, dia_usuario, card, texto + destaques)
                enviados[usuario["codigo"]] = {
                    "enviado_em": datetime.now(FUSO_BRT).replace(microsecond=0).isoformat(),
                    "com_texto": bool(texto),
                }
                salvar_enviados(hoje, enviados)  # a cada usuário: se cair no meio, ninguém recebe duas vezes
                contagem["enviados"] += 1
                contagem["com texto do Claude"] += bool(texto)
            else:  # prévia local: aqui o conteúdo aparece, porque é para o dono conferir
                mensagens = texto + destaques
                print(f"\n=== Prévia {posicao}/{len(usuarios)} · card: {card} · texto do Claude: {bool(texto)} ===")
                for i, mensagem in enumerate(mensagens, 1):
                    print(f"--- mensagem {i}/{len(mensagens)} ({len(mensagem)} caracteres) ---\n{mensagem}")
        except Exception as erro:  # um usuário com problema não impede os outros
            falhas[descrever_falha(erro)] += 1

    resumo = " | ".join(f"{nome}: {total}" for nome, total in contagem.items())
    print(f"Usuários: {len(usuarios)} | {resumo} | edição do Claude: {'sim' if edicao else 'não'} | falhas: {sum(falhas.values())}")
    for motivo, total in falhas.items():
        print(f"  falha: {motivo} x{total}")
    if falhas or contagem["sem card"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
