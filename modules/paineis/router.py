"""Painéis: dados (JSON, com login) e a página (HTML estático; os dados só vêm com o token)."""
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select

from core.db import usar_tenant
from core.security.rbac import Contexto, exige_permissao
from modules.paineis import caixa as painel_caixa
from modules.paineis import fornecedores as painel_fornecedores
from modules.tenants.models import Loja

router = APIRouter(tags=["painéis"])
PAGINAS = Path(__file__).parent / "static"
_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _lojas_visiveis(ctx: Contexto, tenant_id: int) -> list[int]:
    lojas = ctx.db.scalars(select(Loja).where(Loja.tenant_id == tenant_id)).all()
    visiveis = [l.id for l in lojas if ctx.pode("dashboards:ler", tenant_id, l.id)]
    if not visiveis:
        raise HTTPException(status_code=403, detail="Sem acesso aos painéis desse cliente")
    usar_tenant(ctx.db, tenant_id)
    return visiveis


def _exige_banco(ctx: Contexto, tenant_id: int) -> None:
    """A visão caixa vem do extrato: exige `banco:ler` (gestor de loja não vê o banco)."""
    ctx.exigir("banco:ler", tenant_id)
    usar_tenant(ctx.db, tenant_id)


@router.get("/tenants/{tenant_id}/paineis/fornecedores/meses")
def meses_fornecedores(tenant_id: int, visao: Literal["competencia", "caixa"] = "competencia",
                       ctx: Contexto = Depends(exige_permissao("dashboards:ler"))):
    if visao == "caixa":
        _exige_banco(ctx, tenant_id)
        return painel_caixa.meses_disponiveis(ctx.db, tenant_id)
    return painel_fornecedores.meses_disponiveis(ctx.db, _lojas_visiveis(ctx, tenant_id))


@router.get("/tenants/{tenant_id}/paineis/fornecedores")
def painel_de_fornecedores(tenant_id: int, meses: list[str] = Query(...),
                           visao: Literal["competencia", "caixa"] = "competencia",
                           ctx: Contexto = Depends(exige_permissao("dashboards:ler"))):
    meses = sorted(set(meses))
    if not meses or len(meses) > 24 or any(not _MES.match(m) for m in meses):
        raise HTTPException(status_code=422, detail="Informe de 1 a 24 meses no formato AAAA-MM")
    if visao == "caixa":
        _exige_banco(ctx, tenant_id)
        return painel_caixa.montar(ctx.db, tenant_id, meses)
    return painel_fornecedores.montar(ctx.db, tenant_id, _lojas_visiveis(ctx, tenant_id), meses)


@router.get("/painel", include_in_schema=False)
def pagina_painel():
    return FileResponse(PAGINAS / "painel_fornecedores.html", media_type="text/html")


@router.get("/", include_in_schema=False)
def inicio():
    return RedirectResponse("/painel")
