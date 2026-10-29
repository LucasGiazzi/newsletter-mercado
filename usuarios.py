"""Configuração de usuários: variável USUARIOS_YAML (Secret no Actions) ou arquivo usuarios.yml.

Formato em usuarios.example.yml. Nada daqui pode aparecer em log: só contagens.
"""

import os
import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent
ARQUIVO_USUARIOS = RAIZ / "usuarios.yml"


def ler_configuracao():
    """Texto YAML: a variável de ambiente tem prioridade sobre o arquivo."""
    texto = os.environ.get("USUARIOS_YAML", "").strip()
    if texto:
        return texto
    if ARQUIVO_USUARIOS.exists():
        return ARQUIVO_USUARIOS.read_text(encoding="utf-8")
    raise SystemExit("Nenhum usuário configurado: crie usuarios.yml (veja usuarios.example.yml) ou defina USUARIOS_YAML.")


def validar(item):
    """Usuário normalizado, ou None se faltar discord_id (só dígitos) ou lista de tickers."""
    if not isinstance(item, dict) or not isinstance(item.get("tickers"), list):
        return None
    discord_id = str(item.get("discord_id", "")).strip()
    tickers = [str(t).strip().upper() for t in item["tickers"] if str(t).strip()]
    temas = item.get("temas") if isinstance(item.get("temas"), list) else []
    if not discord_id.isdigit() or not tickers:
        return None
    return {
        "nome": str(item.get("nome", "")),
        "discord_id": discord_id,
        "tickers": list(dict.fromkeys(tickers)),
        "temas": [str(t).strip() for t in temas if str(t).strip()],
    }


def carregar_usuarios():
    try:
        dados = yaml.safe_load(ler_configuracao()) or {}
    except yaml.YAMLError as erro:
        # A mensagem do YAML pode citar trechos da configuração: só o tipo vai para o log
        raise SystemExit(f"Configuração de usuários inválida ({type(erro).__name__}).") from None

    itens = dados.get("usuarios") if isinstance(dados, dict) else None
    itens = itens if isinstance(itens, list) else []
    usuarios = [u for u in map(validar, itens) if u]
    if len(usuarios) < len(itens):
        print(f"Aviso: {len(itens) - len(usuarios)} usuário(s) sem discord_id ou tickers foram ignorados.", file=sys.stderr)
    if not usuarios:
        raise SystemExit("Nenhum usuário válido na configuração.")
    return usuarios


def todos_os_tickers(usuarios):
    """União dos tickers de todos os usuários, cada um uma vez."""
    return sorted({t for u in usuarios for t in u["tickers"]})
