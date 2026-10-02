"""Conciliação banco × GCOM: rodar o motor, resumo por mês e lista. Exige `conciliacao:*` E `banco:ler`
(a conciliação mostra o extrato; gestor de loja não vê o banco)."""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from core.audit import registrar
from core.db import usar_tenant
from core.security.rbac import Contexto, exige_permissao
from modules.conciliacao import servico

router = APIRouter(tags=["conciliação"])
_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _acesso(ctx: Contexto, tenant_id: int, permissao: str) -> None:
    ctx.exigir(permissao, tenant_id)
    ctx.exigir("banco:ler", tenant_id)
    usar_tenant(ctx.db, tenant_id)


@router.post("/tenants/{tenant_id}/conciliacao/rodar")
def rodar_motor(tenant_id: int, ctx: Contexto = Depends(exige_permissao("conciliacao:operar"))):
    _acesso(ctx, tenant_id, "conciliacao:operar")
    cont = servico.rodar(ctx.db, tenant_id)
    registrar(ctx.db, "conciliacao.motor", "conciliacoes", tenant_id=tenant_id, usuario_id=ctx.usuario.id,
              detalhes=cont)
    ctx.db.commit()
    return cont


@router.get("/tenants/{tenant_id}/conciliacao/resumo")
def resumo(tenant_id: int, ctx: Contexto = Depends(exige_permissao("conciliacao:ler"))):
    _acesso(ctx, tenant_id, "conciliacao:ler")
    return servico.resumo(ctx.db, tenant_id)


@router.get("/tenants/{tenant_id}/conciliacao")
def listar(tenant_id: int, status: Literal["batido", "sugerido", "pendente", "investigar", "descartado"] | None = None,
           mes: str | None = None, ctx: Contexto = Depends(exige_permissao("conciliacao:ler"))):
    if mes is not None and not _MES.match(mes):
        raise HTTPException(status_code=422, detail="mes no formato AAAA-MM")
    _acesso(ctx, tenant_id, "conciliacao:ler")
    return servico.listar(ctx.db, tenant_id, status, mes)
