"""Lê os comandos que cada usuário mandou na DM do bot e atualiza a lista de ações dele.

Roda antes da coleta (Actions, 7h30): o que foi pedido desde a última leitura já vale na
edição da manhã. Os comandos podem ser mandados a qualquer hora; são aplicados na ordem em que
foram enviados, desde a última leitura.

    /add PETR4 VALE3    /del MGLU3    /list    /ajuda    (também com ! ou sem prefixo)

Só usuários cadastrados em USUARIOS_YAML/usuarios.yml são lidos (o cadastro é o controle
de acesso). As listas ficam em estado/preferencias.json, por código do usuário.
Logs só com contagens (privacidade).
Projeto informativo: não é recomendação de compra, venda ou manutenção de ativos.
"""

import os
import re
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from collect import ErroColeta, buscar_cotacao, criar_sessao_brapi
from discord_api import ErroDiscord, abrir_dm, criar_sessao, enviar_mensagem, ler_mensagens
from usuarios import carregar_usuarios, ler_preferencias, salvar_preferencias

RAIZ = Path(__file__).resolve().parent

LIMITE_ACOES = 20  # por usuário: protege a cota de 15 mil requisições/mês da brapi
FORMATO_TICKER = re.compile(r"^[A-Z]{4}\d{1,2}$")
LINHA_COMANDO = re.compile(r"^\s*[/!]?(add|adicionar|del|delete|remover|list|lista|ajuda|help)\b(.*)$", re.IGNORECASE)
ACOES = {
    "add": "add", "adicionar": "add",
    "del": "del", "delete": "del", "remover": "del",
    "list": "list", "lista": "list",
    "ajuda": "ajuda", "help": "ajuda",
}

AJUDA = (
    "**Comandos da newsletter**\n"
    "- `/add PETR4 VALE3` adiciona ações à sua lista\n"
    "- `/del MGLU3` remove ações\n"
    "- `/list` mostra sua lista\n"
    "- `/ajuda` mostra esta mensagem\n"
    "Pode mandar a qualquer hora. Os comandos são lidos uma vez por dia, às 7h30, antes da edição da manhã: "
    "o que você pedir até lá já vale na edição do dia, e a confirmação chega junto. "
    f"Máximo de {LIMITE_ACOES} ações."
)
BOAS_VINDAS = "Olá! Você vai receber aqui, todo dia útil, o resumo do mercado com as suas ações.\n\n"


# ---------- interpretação ----------

def interpretar(texto):
    """Comandos de uma mensagem: [(ação, [tickers])]. Uma linha por comando; o resto é ignorado."""
    comandos = []
    for linha in texto.splitlines():
        achado = LINHA_COMANDO.match(linha)
        if achado:
            tickers = [t.upper() for t in re.findall(r"[A-Za-z0-9]+", achado.group(2))]
            comandos.append((ACOES[achado.group(1).lower()], tickers))
    return comandos


def ticker_existe(sessao_brapi, ticker, cache):
    """Confere na brapi. 404 = não existe; outra falha (limite, rede) aceita e deixa a coleta avisar."""
    if ticker not in cache:
        try:
            buscar_cotacao(sessao_brapi, ticker)
            cache[ticker] = True
        except ErroColeta as erro:
            cache[ticker] = "HTTP 404" not in str(erro)
    return cache[ticker]


def aplicar(tickers, comandos, existe):
    """Aplica os comandos na ordem em que foram mandados; devolve a nova lista e o resumo."""
    lista = list(tickers)
    resumo = {"adicionadas": [], "removidas": [], "invalidas": [], "acima_do_limite": [], "nao_estavam": [], "ajuda": False}
    for acao, alvos in comandos:
        if acao == "ajuda":
            resumo["ajuda"] = True
        elif acao == "add":
            for ticker in alvos:
                if ticker in lista:
                    continue
                if not FORMATO_TICKER.match(ticker) or not existe(ticker):
                    resumo["invalidas"].append(ticker)
                elif len(lista) >= LIMITE_ACOES:
                    resumo["acima_do_limite"].append(ticker)
                else:
                    lista.append(ticker)
                    resumo["adicionadas"].append(ticker)
        elif acao == "del":
            for ticker in alvos:
                if ticker in lista:
                    lista.remove(ticker)
                    resumo["removidas"].append(ticker)
                else:
                    resumo["nao_estavam"].append(ticker)
    return lista, resumo


def montar_resposta(lista, resumo):
    mudou = resumo["adicionadas"] or resumo["removidas"]
    linhas = ["**Sua lista foi atualizada**" if mudou else "**Comandos recebidos**"]
    if resumo["adicionadas"]:
        linhas.append(f"➕ Adicionadas: {', '.join(resumo['adicionadas'])}")
    if resumo["removidas"]:
        linhas.append(f"➖ Removidas: {', '.join(resumo['removidas'])}")
    if resumo["invalidas"]:
        linhas.append(f"⚠️ Não encontradas na B3: {', '.join(resumo['invalidas'])}")
    if resumo["acima_do_limite"]:
        linhas.append(f"⚠️ Limite de {LIMITE_ACOES} ações; ficaram de fora: {', '.join(resumo['acima_do_limite'])}")
    if resumo["nao_estavam"]:
        linhas.append(f"ℹ️ Não estavam na lista: {', '.join(resumo['nao_estavam'])}")
    if lista:
        linhas.append(f"📋 Sua lista ({len(lista)}): {', '.join(lista)}")
    else:
        linhas.append("📋 Sua lista está vazia: você não recebe a edição até adicionar ações com `/add`.")
    if mudou:
        linhas.append("Vale a partir da edição de hoje.")
    if resumo["ajuda"]:
        linhas.append(f"\n{AJUDA}")
    return "\n".join(linhas)


# ---------- por usuário ----------

def processar_usuario(sessao, usuario, entrada, existe, contagem):
    """Lê a DM desde a última leitura, aplica os comandos e responde. Atualiza 'entrada'."""
    canal = abrir_dm(sessao, usuario["discord_id"])
    if not entrada.get("apresentado"):
        enviar_mensagem(sessao, canal, BOAS_VINDAS + AJUDA)
        entrada["apresentado"] = True
        contagem["boas-vindas"] += 1

    mensagens = ler_mensagens(sessao, canal, entrada.get("cursor", "0"))
    comandos = [
        comando
        for mensagem in mensagens
        if mensagem.get("author", {}).get("id") == usuario["discord_id"]  # ignora as mensagens do próprio bot
        for comando in interpretar(mensagem.get("content", ""))
    ]
    if comandos:
        lista, resumo = aplicar(usuario["tickers"], comandos, existe)
        entrada["tickers"] = lista
        enviar_mensagem(sessao, canal, montar_resposta(lista, resumo))
        contagem["usuários com comandos"] += 1
        contagem["comandos"] += len(comandos)
        contagem["tickers inválidos"] += len(resumo["invalidas"])
    if mensagens:  # só avança depois de aplicar: se algo falhar antes, os comandos são relidos amanhã
        entrada["cursor"] = mensagens[-1]["id"]


def descrever_falha(erro):
    """Motivo da falha para o log, sem dados do usuário."""
    return str(erro) if isinstance(erro, ErroDiscord) else type(erro).__name__


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    load_dotenv(RAIZ / ".env")
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN não definido.")

    usuarios = carregar_usuarios()
    preferencias = ler_preferencias()
    sessao = criar_sessao(token)
    sessao_brapi, cache = criar_sessao_brapi(), {}

    def existe(ticker):
        return ticker_existe(sessao_brapi, ticker, cache)

    contagem, falhas = Counter(), Counter()
    for usuario in usuarios:
        entrada = preferencias.setdefault(usuario["codigo"], {})
        try:
            processar_usuario(sessao, usuario, entrada, existe, contagem)
        except Exception as erro:  # um usuário com problema não impede os outros
            falhas[descrever_falha(erro)] += 1
    salvar_preferencias(preferencias)

    resumo = " | ".join(f"{nome}: {total}" for nome, total in contagem.items()) or "nenhum comando"
    print(f"Usuários: {len(usuarios)} | {resumo} | falhas: {sum(falhas.values())}")
    for motivo, total in falhas.items():
        print(f"  falha: {motivo} x{total}")
    if falhas:
        sys.exit(1)


if __name__ == "__main__":
    main()
