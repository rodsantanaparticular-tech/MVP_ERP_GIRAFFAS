"""Comandos administrativos (rodam dentro do contêiner da API).

  docker compose exec api python -m core.cli criar-admin --email voce@exemplo.com --nome "Seu Nome"

A senha é pedida no terminal (não aparece na tela e não fica no histórico).
"""
import argparse
import getpass
import os
import sys

from sqlalchemy import func, select

import modules.models  # noqa: F401
from core.audit import registrar
from core.config import settings
from core.db import nova_sessao
from core.security.auth import hash_senha
from modules.identity.models import PapelAcesso, Usuario, UsuarioPapel


def criar_admin(email: str, nome: str) -> None:
    senha = os.environ.get("ERP_ADMIN_SENHA") or getpass.getpass("Senha do administrador: ")
    if len(senha) < settings.senha_min_caracteres:
        sys.exit(f"Senha precisa ter pelo menos {settings.senha_min_caracteres} caracteres.")
    with nova_sessao() as db:
        email = email.strip().lower()
        u = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email))
        if u is None:
            u = Usuario(email=email, nome=nome, senha_hash=hash_senha(senha), ativo=True)
            db.add(u)
            db.flush()
        papel = db.scalar(select(PapelAcesso).where(PapelAcesso.codigo == "plataforma_admin"))
        if not db.scalar(select(UsuarioPapel).where(UsuarioPapel.usuario_id == u.id,
                                                    UsuarioPapel.papel_id == papel.id)):
            db.add(UsuarioPapel(usuario_id=u.id, papel_id=papel.id))
        registrar(db, "admin_criado_cli", "usuario", u.id, usuario_id=u.id)
        db.commit()
        print(f"OK: {email} é administrador da plataforma (usuário id={u.id}).")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m core.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("criar-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--nome", required=True)
    args = p.parse_args()
    if args.cmd == "criar-admin":
        criar_admin(args.email, args.nome)


if __name__ == "__main__":
    main()
