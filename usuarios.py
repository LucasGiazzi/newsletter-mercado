"""Configuração de usuários: variável USUARIOS_YAML (Secret no Actions) ou arquivo usuarios.yml.

O YAML diz quem recebe a edição e a lista inicial de ações. As mudanças feitas pelos
comandos /add e /del (comandos.py) ficam em estado/preferencias.json, indexadas pelo
código do usuário (hash do discord_id), e prevalecem sobre a lista do YAML.
Formato em usuarios.example.yml. Nada daqui pode aparecer em log: só contagens.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent
ARQUIVO_USUARIOS = RAIZ / "usuarios.yml"
ARQUIVO_PREFERENCIAS = RAIZ / "estado" / "preferencias.json"


def codigo_do_usuario(discord_id):
    """Código curto e estável para nomear arquivos e preferências sem expor o discord_id.

    Não usar a posição na lista: se ela mudar, um usuário receberia dados de outro.
    """
    return hashlib.sha256(discord_id.encode()).hexdigest()[:10]


# ---------- preferências (listas alteradas por comando) ----------

def ler_preferencias():
    if not ARQUIVO_PREFERENCIAS.exists():
        return {}
    return json.loads(ARQUIVO_PREFERENCIAS.read_text(encoding="utf-8"))


def salvar_preferencias(preferencias):
    ARQUIVO_PREFERENCIAS.parent.mkdir(exist_ok=True)
    texto = json.dumps(preferencias, ensure_ascii=False, indent=2, sort_keys=True)
    ARQUIVO_PREFERENCIAS.write_text(texto + "\n", encoding="utf-8")


# ---------- configuração ----------

def ler_configuracao():
    """Texto YAML: a variável de ambiente tem prioridade sobre o arquivo."""
    texto = os.environ.get("USUARIOS_YAML", "").strip()
    if texto:
        return texto
    if ARQUIVO_USUARIOS.exists():
        return ARQUIVO_USUARIOS.read_text(encoding="utf-8")
    raise SystemExit("Nenhum usuário configurado: crie usuarios.yml (veja usuarios.example.yml) ou defina USUARIOS_YAML.")


def validar(item):
    """Usuário normalizado, ou None se faltar discord_id (só dígitos). Lista vazia é válida."""
    if not isinstance(item, dict):
        return None
    discord_id = str(item.get("discord_id", "")).strip()
    if not discord_id.isdigit():
        return None
    tickers = item.get("tickers") if isinstance(item.get("tickers"), list) else []
    temas = item.get("temas") if isinstance(item.get("temas"), list) else []
    return {
        "nome": str(item.get("nome", "")),
        "discord_id": discord_id,
        "codigo": codigo_do_usuario(discord_id),
        "tickers": list(dict.fromkeys(str(t).strip().upper() for t in tickers if str(t).strip())),
        "temas": [str(t).strip() for t in temas if str(t).strip()],
        "texto_claude": item.get("texto_claude") is True,  # opcional: recebe o texto da edicao/
    }


def carregar_usuarios():
    """Usuários do YAML, com a lista de ações das preferências quando houver."""
    try:
        dados = yaml.safe_load(ler_configuracao()) or {}
    except yaml.YAMLError as erro:
        # A mensagem do YAML pode citar trechos da configuração: só o tipo vai para o log
        raise SystemExit(f"Configuração de usuários inválida ({type(erro).__name__}).") from None

    itens = dados.get("usuarios") if isinstance(dados, dict) else None
    itens = itens if isinstance(itens, list) else []
    usuarios = [u for u in map(validar, itens) if u]
    if len(usuarios) < len(itens):
        print(f"Aviso: {len(itens) - len(usuarios)} usuário(s) sem discord_id válido foram ignorados.", file=sys.stderr)
    if not usuarios:
        raise SystemExit("Nenhum usuário válido na configuração.")

    preferencias = ler_preferencias()
    for usuario in usuarios:
        alterada = preferencias.get(usuario["codigo"], {}).get("tickers")
        if alterada is not None:
            usuario["tickers"] = alterada
    return usuarios


def todos_os_tickers(usuarios):
    """União dos tickers de todos os usuários, cada um uma vez."""
    return sorted({t for u in usuarios for t in u["tickers"]})


def filtrar_para_usuario(dia, usuario, todos):
    """Cópia do JSON só com os ativos do usuário; erros de tickers de outros usuários não aparecem."""
    meus = set(usuario["tickers"])

    def erro_visivel(erro):
        origem = erro.split(":")[0]
        return origem in meus or origem not in todos  # macro e índices valem para todos

    ativos = [a for a in dia["ativos"] if a["ticker"] in meus]
    erros = [e for e in dia["erros"] if erro_visivel(e)]
    if dia["status"] == "sem_pregao":
        status = "sem_pregao"
    elif erros or any(not a["dado_do_pregao"] for a in ativos):
        status = "parcial"
    else:
        status = "ok"
    return {**dia, "ativos": ativos, "erros": erros, "status": status}
