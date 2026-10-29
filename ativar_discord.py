"""Ativação única do bot do Discord.

O Discord exige que um bot novo se conecte ao Gateway (a conexão em tempo real) pelo menos
uma vez antes de enviar mensagens pela API. Este script conecta, se identifica e sai.

Uso, uma vez, na sua máquina:
    pip install websocket-client
    python ativar_discord.py

Lê DISCORD_BOT_TOKEN do .env e nunca imprime o token. websocket-client não está no
requirements.txt porque o Actions não precisa dele.
"""

import json
import os
import sys
from pathlib import Path

import websocket
from dotenv import load_dotenv

GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
IDENTIFICAR = 2
SESSAO_INVALIDA = 9


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows não é UTF-8 por padrão
    load_dotenv(Path(__file__).resolve().parent / ".env")
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN não definido no .env.")

    try:
        conexao = websocket.create_connection(GATEWAY, timeout=20)
    except (websocket.WebSocketException, OSError) as erro:
        raise SystemExit(f"Falha ao conectar no Gateway ({type(erro).__name__}).") from None
    try:
        conexao.recv()  # Hello
        propriedades = {"os": sys.platform, "browser": "newsletter-mercado", "device": "newsletter-mercado"}
        conexao.send(json.dumps({"op": IDENTIFICAR, "d": {"token": token, "intents": 0, "properties": propriedades}}))
        while True:
            evento = json.loads(conexao.recv())
            if evento.get("t") == "READY":
                print(f"Bot ativado: {evento['d']['user']['username']}. Não precisa rodar de novo.")
                return
            if evento.get("op") == SESSAO_INVALIDA:
                raise SystemExit("O Discord recusou a sessão. Confira o DISCORD_BOT_TOKEN.")
    except (websocket.WebSocketException, OSError):
        # Código 4004 (token inválido) fecha a conexão sem mensagem legível
        raise SystemExit("O Discord fechou a conexão. Confira o DISCORD_BOT_TOKEN.") from None
    finally:
        conexao.close()


if __name__ == "__main__":
    main()
