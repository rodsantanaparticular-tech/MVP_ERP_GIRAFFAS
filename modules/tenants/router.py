from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from core.audit import registrar
from core.security.rbac import Contexto, exige_permissao
from modules.tenants.models import Loja, Rede, Tenant

router = APIRouter(tags=["clientes e lojas"])


class TenantIn(BaseModel):
    rede_codigo: str
    rede_nome: str | None = None
    codigo: str
    razao_social: str
    cnpj: str | None = None


class LojaIn(BaseModel):
    nome: str
    filial_sigla: str | None = None
    razao_social: str | None = None
    cnpj: str | None = None


@router.get("/tenants")
def listar_tenants(ctx: Contexto = Depends(exige_permissao("dashboards:ler"))):
    visiveis = set()
    for perm in {a.permissao for a in ctx.atribuicoes}:
        t = ctx.tenants_com(perm)
        if t is None:
            visiveis = None
            break
        visiveis |= t
    q = select(Tenant).order_by(Tenant.id)
    if visiveis is not None:
        q = q.where(Tenant.id.in_(visiveis))
    return [{"id": t.id, "codigo": t.codigo, "razao_social": t.razao_social, "status": t.status}
            for t in ctx.db.scalars(q)]


@router.post("/tenants", status_code=201)
def criar_tenant(dados: TenantIn, request: Request, ctx: Contexto = Depends(exige_permissao("plataforma:admin"))):
    db = ctx.db
    rede = db.scalar(select(Rede).where(Rede.codigo == dados.rede_codigo))
    if rede is None:
        rede = Rede(codigo=dados.rede_codigo, nome=dados.rede_nome or dados.rede_codigo)
        db.add(rede)
        db.flush()
    if db.scalar(select(Tenant).where(Tenant.codigo == dados.codigo)):
        raise HTTPException(status_code=409, detail="Código de cliente já existe")
    t = Tenant(rede_id=rede.id, codigo=dados.codigo, razao_social=dados.razao_social, cnpj=dados.cnpj,
               status="onboarding")
    db.add(t)
    db.flush()
    registrar(db, "tenant_criado", "tenant", t.id, usuario_id=ctx.usuario.id, tenant_id=t.id,
              ip=request.client.host if request.client else None)
    db.commit()
    return {"id": t.id, "codigo": t.codigo}


@router.get("/tenants/{tenant_id}/lojas")
def listar_lojas(tenant_id: int, ctx: Contexto = Depends(exige_permissao("dashboards:ler"))):
    lojas =ctx.db.scalars(select(Loja).where(Loja.tenant_id == tenant_id).order_by(Loja.id)).all()
    # gestor de loja só enxerga a(s) própria(s) loja(s)
    lojas = [l for l in lojas if ctx.pode("dashboards:ler", tenant_id, l.id)]
    if not lojas and not ctx.pode("dashboards:ler", tenant_id):
        raise HTTPException(status_code=403, detail="Sem acesso a esse cliente")
    return [{"id": l.id, "nome": l.nome, "filial_sigla": l.filial_sigla, "ativo": l.ativo} for l in lojas]


@router.post("/tenants/{tenant_id}/lojas", status_code=201)
def criar_loja(tenant_id: int, dados: LojaIn, request: Request,
               ctx: Contexto = Depends(exige_permissao("tenants:gerir"))):
    ctx.exigir("tenants:gerir", tenant_id)
    db = ctx.db
    if db.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Cliente inexistente")
    loja = Loja(tenant_id=tenant_id, nome=dados.nome, filial_sigla=dados.filial_sigla,
                razao_social=dados.razao_social, cnpj=dados.cnpj, ativo=True)
    db.add(loja)
    db.flush()
    registrar(db, "loja_criada", "loja", loja.id, usuario_id=ctx.usuario.id, tenant_id=tenant_id,
              ip=request.client.host if request.client else None)
    db.commit()
    return {"id": loja.id, "nome": loja.nome}
