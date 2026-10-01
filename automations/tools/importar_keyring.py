"""Leva UMA senha do Gerenciador de Credenciais do Windows (keyring) para o
cofre do IN-360, sem que ela apareça na tela, em arquivo ou em log.

Roda no Windows (fora do Docker), onde as senhas já estão:

    py automations\\tools\\importar_keyring.py --conexao-id 3 --tipo password ^
        --keyring-target GCOM_Rodiza --keyring-user <usuario>

Pede o seu login do IN-360 (e-mail + senha) para autorizar a gravação. A
conexão precisa existir antes (POST /tenants/{id}/conexoes). O keyring NÃO é
apagado: os scripts atuais continuam funcionando durante a transição.
"""
import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request

import keyring


def _req(metodo: str, url: str, corpo: dict | None = None, token: str | None = None) -> dict:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    r = urllib.request.Request(url, data=dados, method=metodo, headers={"Content-Type": "application/json"})
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"Erro {e.code}: {e.read().decode(errors='replace')}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://127.0.0.1:8100")
    p.add_argument("--conexao-id", type=int, required=True)
    p.add_argument("--tipo", required=True, help="ex.: password, imap_app_password")
    p.add_argument("--keyring-target", required=True)
    p.add_argument("--keyring-user", required=True)
    a = p.parse_args()

    segredo = keyring.get_password(a.keyring_target, a.keyring_user)
    if not segredo:
        sys.exit(f"Nada no keyring para {a.keyring_target} / {a.keyring_user}.")

    email = input("Seu e-mail no IN-360: ").strip()
    senha = getpass.getpass("Sua senha do IN-360 (não aparece): ")
    token = _req("POST", f"{a.api}/auth/login", {"email": email, "senha": senha})["access_token"]

    meta = _req("PUT", f"{a.api}/conexoes/{a.conexao_id}/credenciais/{a.tipo}", {"valor": segredo}, token)
    print(f"OK: '{a.tipo}' gravado no cofre (versão {meta['versao']}, impressão {meta['impressao']}).")


if __name__ == "__main__":
    main()
