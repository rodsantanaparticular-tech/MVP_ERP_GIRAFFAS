"""Perfis de acesso: papel → permissões ("modulo:acao"), atribuído por escopo.

Escopo da atribuição (usuario_papel):
  tenant_id NULL, loja_id NULL  → plataforma (todos os clientes)
  tenant_id T,    loja_id NULL  → todo o cliente T
  tenant_id T,    loja_id L     → só a loja L
"""
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import get_db
from core.security.auth import usuario_atual
from modules.identity.models import PapelAcesso, PapelPermissao, Permissao, UsuarioPapel, Usuario


@dataclass(frozen=True)
class Atribuicao:
    permissao: str
    tenant_id: int | None
    loja_id: int | None


def carregar_atribuicoes(db: Session, usuario_id: int) -> list[Atribuicao]:
    linhas = db.execute(
        select(Permissao.codigo, UsuarioPapel.tenant_id, UsuarioPapel.loja_id)
        .join(PapelPermissao, PapelPermissao.permissao_id == Permissao.id)
        .join(UsuarioPapel, UsuarioPapel.papel_id == PapelPermissao.papel_id)
        .where(UsuarioPapel.usuario_id == usuario_id)
    ).all()
    return [Atribuicao(*l) for l in linhas]


def carregar_papeis(db: Session, usuario_id: int) -> list[tuple[str, int | None, int | None]]:
    return [tuple(l) for l in db.execute(
        select(PapelAcesso.codigo, UsuarioPapel.tenant_id, UsuarioPapel.loja_id)
        .join(UsuarioPapel, UsuarioPapel.papel_id == PapelAcesso.id)
        .where(UsuarioPapel.usuario_id == usuario_id)
    ).all()]


@dataclass
class Contexto:
    usuario: Usuario
    db: Session
    atribuicoes: list[Atribuicao] = field(default_factory=list)

    def pode(self, permissao: str, tenant_id: int | None = None, loja_id: int | None = None) -> bool:
        for a in self.atribuicoes:
            if a.permissao != permissao:
                continue
            if a.tenant_id is None:                      # plataforma
                return True
            if tenant_id is None or a.tenant_id != tenant_id:
                continue
            if a.loja_id is None or a.loja_id == loja_id:  # cliente todo, ou a própria loja
                return True
        return False

    def exigir(self, permissao: str, tenant_id: int | None = None, loja_id: int | None = None) -> None:
        if not self.pode(permissao, tenant_id, loja_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Sem permissão '{permissao}' neste escopo")

    def tenants_com(self, permissao: str) -> set[int] | None:
        """None = todos (escopo plataforma); senão, os tenants onde há a permissão."""
        ids = set()
        for a in self.atribuicoes:
            if a.permissao == permissao:
                if a.tenant_id is None:
                    return None
                ids.add(a.tenant_id)
        return ids


def exige_permissao(permissao: str):
    """Dependência FastAPI: barra quem não tem a permissão em escopo nenhum. O
    endpoint ainda chama ctx.exigir(...) com o tenant/loja concretos."""
    def dependencia(usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)) -> Contexto:
        ctx = Contexto(usuario=usuario, db=db, atribuicoes=carregar_atribuicoes(db, usuario.id))
        if not any(a.permissao == permissao for a in ctx.atribuicoes):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Sem permissão '{permissao}'")
        return ctx
    return dependencia
