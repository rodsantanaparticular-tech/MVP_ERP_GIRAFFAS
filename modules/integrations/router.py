"""Integrações e cofre de senhas.

Regra de ouro: nenhuma resposta traz segredo, exceto /revelar (permissão
própria + motivo obrigatório + registro em credencial_acessos e audit_log).
"""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update

from core.audit import registrar
from core.db import usar_tenant
from core.security.rbac import Contexto, exige_permissao
from core.security.vault import Cofre
from modules.integrations.models import Conexao, Credencial, Integracao
from modules.tenants.models import Loja

router = APIRouter(tags=["integrações e cofre de senhas"])

# chaves que denunciam segredo em `parametros` (que não é cifrado)
_PARECE_SEGREDO = re.compile(r"senha|password|passwd|secret|token|api[_-]?key|chave|pin|pfx|certificado",
                             re.IGNORECASE)


class ConexaoIn(BaseModel):
    integracao: str
    nome: str
    loja_id: int | None = None
    parametros: dict = Field(default_factory=dict)


class ConexaoPatch(BaseModel):
    nome: str | None = None
    parametros: dict | None = None
    ativo: bool | None = None


class CredencialIn(BaseModel):
    valor: str = Field(min_length=1)
    expira_em: datetime | None = None


class RevelarIn(BaseModel):
    motivo: str = Field(min_length=10)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _valida_parametros(integ: Integracao, parametros: dict) -> None:
    suspeitas = [k for k in parametros if _PARECE_SEGREDO.search(k)]
    if suspeitas:
        raise HTTPException(status_code=422, detail=(
            f"Parâmetros parecem conter segredo ({', '.join(suspeitas)}). "
            "Senhas e chaves vão no cofre: PUT /conexoes/{id}/credenciais/{tipo}"))
    faltando = [k for k in integ.schema_parametros.get("required", []) if not parametros.get(k)]
    if faltando:
        raise HTTPException(status_code=422, detail=f"Parâmetros obrigatórios ausentes: {', '.join(faltando)}")


def _conexao(ctx: Contexto, conexao_id: int, permissao: str) -> Conexao:
    """Carrega a conexão respeitando RLS. conexao_tenant() (SECURITY DEFINER)
    devolve só o tenant dono; a permissão é checada antes de abrir a linha."""
    tenant_id = ctx.db.scalar(text("SELECT conexao_tenant(:id)"), {"id": conexao_id})
    permitidos = ctx.tenants_com(permissao)  # None = plataforma
    if tenant_id is None or (permitidos is not None and tenant_id not in permitidos):
        # 404 também para cliente alheio: não revela que a conexão existe
        raise HTTPException(status_code=404, detail="Conexão inexistente")
    usar_tenant(ctx.db, tenant_id)
    con = ctx.db.get(Conexao, conexao_id)
    if con is None:
        raise HTTPException(status_code=404, detail="Conexão inexistente")
    ctx.exigir(permissao, con.tenant_id, con.loja_id)
    return con


def _meta(c: Credencial) -> dict:
    return {"tipo": c.tipo, "versao": c.versao, "ativo": c.ativo, "impressao": c.fingerprint[:12],
            "criado_em": c.criado_em, "criado_por": c.criado_por, "expira_em": c.expira_em,
            "rotacionado_em": c.rotacionado_em}


# --- catálogo ---------------------------------------------------------------------
@router.get("/integracoes")
def catalogo(ctx: Contexto = Depends(exige_permissao("conexoes:ler"))):
    return [{"codigo": i.codigo, "nome": i.nome, "categoria": i.categoria, "tipo_auth": i.tipo_auth,
             "requer_navegador": i.requer_navegador, "requer_humano": i.requer_humano,
             "segredos_exigidos": i.segredos_exigidos,
             "parametros_obrigatorios": i.schema_parametros.get("required", [])}
            for i in ctx.db.scalars(select(Integracao).where(Integracao.ativo.is_(True)).order_by(Integracao.id))]


# --- conexões -----------------------------------------------------------------------
@router.get("/tenants/{tenant_id}/conexoes")
def listar_conexoes(tenant_id: int, ctx: Contexto = Depends(exige_permissao("conexoes:ler"))):
    ctx.exigir("conexoes:ler", tenant_id)
    usar_tenant(ctx.db, tenant_id)
    linhas = ctx.db.execute(select(Conexao, Integracao.codigo).join(Integracao)
                            .where(Conexao.tenant_id == tenant_id).order_by(Conexao.id)).all()
    saida = []
    for con, cod in linhas:
        creds = ctx.db.scalars(select(Credencial).where(Credencial.conexao_id == con.id,
                                                        Credencial.ativo.is_(True))).all()
        saida.append({"id": con.id, "integracao": cod, "nome": con.nome, "loja_id": con.loja_id,
                      "parametros": con.parametros, "ativo": con.ativo,
                      "segredos_cadastrados": sorted(c.tipo for c in creds),
                      "ultimo_sucesso_em": con.ultimo_sucesso_em})
    return saida


@router.post("/tenants/{tenant_id}/conexoes", status_code=201)
def criar_conexao(tenant_id: int, dados: ConexaoIn, request: Request,
                  ctx: Contexto = Depends(exige_permissao("conexoes:gerir"))):
    ctx.exigir("conexoes:gerir", tenant_id, dados.loja_id)
    db = ctx.db
    integ = db.scalar(select(Integracao).where(Integracao.codigo == dados.integracao, Integracao.ativo.is_(True)))
    if integ is None:
        raise HTTPException(status_code=404, detail="Integração inexistente no catálogo")
    if dados.loja_id is not None:
        loja = db.get(Loja, dados.loja_id)
        if loja is None or loja.tenant_id != tenant_id:
            raise HTTPException(status_code=422, detail="Loja não pertence a esse cliente")
    _valida_parametros(integ, dados.parametros)
    usar_tenant(db, tenant_id)
    con = Conexao(tenant_id=tenant_id, loja_id=dados.loja_id, integracao_id=integ.id, nome=dados.nome,
                  parametros=dados.parametros, ativo=True)
    db.add(con)
    db.flush()
    registrar(db, "conexao_criada", "conexao", con.id, usuario_id=ctx.usuario.id, tenant_id=tenant_id,
              detalhes={"integracao": integ.codigo, "nome": dados.nome}, ip=_ip(request))
    db.commit()
    return {"id": con.id, "integracao": integ.codigo, "segredos_exigidos": integ.segredos_exigidos}


@router.patch("/conexoes/{conexao_id}")
def alterar_conexao(conexao_id: int, dados: ConexaoPatch, request: Request,
                    ctx: Contexto = Depends(exige_permissao("conexoes:gerir"))):
    con = _conexao(ctx, conexao_id, "conexoes:gerir")
    if dados.parametros is not None:
        _valida_parametros(ctx.db.get(Integracao, con.integracao_id), dados.parametros)
        con.parametros = dados.parametros
    if dados.nome is not None:
        con.nome = dados.nome
    if dados.ativo is not None:
        con.ativo = dados.ativo
    registrar(ctx.db, "conexao_alterada", "conexao", con.id, usuario_id=ctx.usuario.id, tenant_id=con.tenant_id,
              detalhes=dados.model_dump(exclude_none=True), ip=_ip(request))
    ctx.db.commit()
    return {"ok": True}


# --- cofre ------------------------------------------------------------------------
@router.get("/conexoes/{conexao_id}/credenciais")
def metadados_credenciais(conexao_id: int, historico: bool = False,
                          ctx: Contexto = Depends(exige_permissao("credenciais:metadados"))):
    con = _conexao(ctx, conexao_id, "credenciais:metadados")
    q = select(Credencial).where(Credencial.conexao_id == con.id)
    if not historico:
        q = q.where(Credencial.ativo.is_(True))
    return [_meta(c) for c in ctx.db.scalars(q.order_by(Credencial.tipo, Credencial.versao.desc()))]


@router.put("/conexoes/{conexao_id}/credenciais/{tipo}")
def gravar_credencial(conexao_id: int, tipo: str, dados: CredencialIn, request: Request,
                      ctx: Contexto = Depends(exige_permissao("credenciais:gravar"))):
    con = _conexao(ctx, conexao_id, "credenciais:gravar")
    integ = ctx.db.get(Integracao, con.integracao_id)
    if tipo not in integ.segredos_exigidos:
        raise HTTPException(status_code=422, detail=(
            f"'{tipo}' não é segredo de {integ.codigo}. Aceitos: {', '.join(integ.segredos_exigidos) or 'nenhum'}"))
    cred = Cofre(ctx.db).gravar(con.tenant_id, con.id, tipo, dados.valor, usuario_id=ctx.usuario.id,
                                expira_em=dados.expira_em)
    registrar(ctx.db, "credencial_gravada", "conexao", con.id, usuario_id=ctx.usuario.id, tenant_id=con.tenant_id,
              detalhes={"tipo": tipo, "versao": cred.versao}, ip=_ip(request))
    ctx.db.commit()
    return _meta(cred)


@router.delete("/conexoes/{conexao_id}/credenciais/{tipo}")
def revogar_credencial(conexao_id: int, tipo: str, request: Request,
                       ctx: Contexto = Depends(exige_permissao("credenciais:gravar"))):
    con = _conexao(ctx, conexao_id, "credenciais:gravar")
    n = ctx.db.execute(update(Credencial).where(Credencial.conexao_id == con.id, Credencial.tipo == tipo,
                                                Credencial.ativo.is_(True))
                       .values(ativo=False, rotacionado_em=datetime.utcnow())).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="Nenhuma credencial ativa desse tipo")
    registrar(ctx.db, "credencial_revogada", "conexao", con.id, usuario_id=ctx.usuario.id, tenant_id=con.tenant_id,
              detalhes={"tipo": tipo}, ip=_ip(request))
    ctx.db.commit()
    return {"ok": True}


@router.post("/conexoes/{conexao_id}/credenciais/{tipo}/revelar")
def revelar_credencial(conexao_id: int, tipo: str, dados: RevelarIn, request: Request,
                       ctx: Contexto = Depends(exige_permissao("credenciais:revelar"))):
    con = _conexao(ctx, conexao_id, "credenciais:revelar")
    try:
        valor = Cofre(ctx.db).ler_ativa(con.tenant_id, con.id, tipo, finalidade=f"revelar: {dados.motivo}",
                                        usuario_id=ctx.usuario.id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Nenhuma credencial ativa desse tipo")
    registrar(ctx.db, "credencial_revelada", "conexao", con.id, usuario_id=ctx.usuario.id, tenant_id=con.tenant_id,
              detalhes={"tipo": tipo, "motivo": dados.motivo}, ip=_ip(request))
    ctx.db.commit()
    return {"tipo": tipo, "valor": valor}
