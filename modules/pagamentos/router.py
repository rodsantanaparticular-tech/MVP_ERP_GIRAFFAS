"""CRM de fornecedores, padrões de pagamento e despesas recorrentes.

Ler: `conciliacao:ler`. Alterar: `parametros:gerir` (cadastro é parâmetro de negócio).
Padrão de pagamento nunca é sobrescrito: trocar fecha o vigente e abre outro.
"""
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.audit import registrar
from core.db import usar_tenant
from core.security.rbac import Contexto, exige_permissao
from modules.pagamentos.models import DespesaRecorrente, Fornecedor, PadraoPagamento
from modules.pagamentos.relatorio_crm import gerar as gerar_relatorio_crm
from modules.tenants.models import Tenant

router = APIRouter(tags=["pagamentos: fornecedores"])

TipoPadrao = Literal["um_para_um", "consolidado_mensal", "agrupado_vencimento", "nota_mais_ajuste", "livre"]


def normalizar_cnpj(valor: str | None) -> str | None:
    if valor is None or not valor.strip():
        return None
    digitos = re.sub(r"\D", "", valor)
    if len(digitos) != 14:
        raise ValueError("CNPJ precisa ter 14 dígitos")
    return digitos


class FornecedorIn(BaseModel):
    nome: str = Field(min_length=1)
    razao_social: str | None = None
    cnpj: str | None = None
    categoria: str | None = None
    apelidos: list[str] = Field(default_factory=list)
    prazo_pagamento: str | None = None
    endereco: str | None = None
    observacoes: str | None = None

    @field_validator("cnpj")
    @classmethod
    def validar_cnpj(cls, v: str | None) -> str | None:
        return normalizar_cnpj(v)


class FornecedorPatch(BaseModel):
    nome: str | None = Field(default=None, min_length=1)
    razao_social: str | None = None
    cnpj: str | None = None
    categoria: str | None = None
    apelidos: list[str] | None = None
    prazo_pagamento: str | None = None
    endereco: str | None = None
    observacoes: str | None = None
    ativo: bool | None = None

    @field_validator("cnpj")
    @classmethod
    def validar_cnpj(cls, v: str | None) -> str | None:
        return normalizar_cnpj(v)


class PadraoIn(BaseModel):
    tipo: TipoPadrao
    janela_dias_antes: int = Field(default=3, ge=0, le=60)
    janela_dias_depois: int = Field(default=5, ge=0, le=60)
    tolerancia_valor: Decimal = Field(default=Decimal("0.00"), ge=0)
    ajuste_max_pct: Decimal | None = Field(default=None, ge=0, le=1)
    parametros: dict = Field(default_factory=dict)
    vigencia_inicio: date | None = None
    observacao: str | None = None


class RecorrenteIn(BaseModel):
    descricao: str = Field(min_length=1)
    fornecedor_id: int | None = None
    dia_inicio: int = Field(ge=1, le=31)
    dia_fim: int = Field(ge=1, le=31)
    valor_min: Decimal | None = Field(default=None, ge=0)
    valor_max: Decimal | None = Field(default=None, ge=0)
    valor_variavel: bool = False
    vigencia_fim: date | None = None
    observacao: str | None = None


class RecorrentePatch(BaseModel):
    descricao: str | None = Field(default=None, min_length=1)
    fornecedor_id: int | None = None
    dia_inicio: int | None = Field(default=None, ge=1, le=31)
    dia_fim: int | None = Field(default=None, ge=1, le=31)
    valor_min: Decimal | None = Field(default=None, ge=0)
    valor_max: Decimal | None = Field(default=None, ge=0)
    valor_variavel: bool | None = None
    vigencia_fim: date | None = None
    observacao: str | None = None
    ativo: bool | None = None


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _commit(ctx: Contexto, conflito: str) -> None:
    try:
        ctx.db.commit()
    except IntegrityError as e:
        ctx.db.rollback()
        raise HTTPException(status_code=409, detail=conflito) from e


def _exigir_leitura(ctx: Contexto, tenant_id: int) -> None:
    """Fornecedores são do cliente todo (as lojas compartilham): quem lê a conciliação
    de QUALQUER loja do cliente pode consultar o cadastro. Alterar exige o cliente todo."""
    if ctx.pode("conciliacao:ler", tenant_id):
        return
    if any(a.permissao == "conciliacao:ler" and a.tenant_id == tenant_id for a in ctx.atribuicoes):
        return
    ctx.exigir("conciliacao:ler", tenant_id)  # levanta o 403 padrão


def _fornecedor(ctx: Contexto, tenant_id: int, fornecedor_id: int) -> Fornecedor:
    usar_tenant(ctx.db, tenant_id)
    f = ctx.db.get(Fornecedor, fornecedor_id)
    if f is None or f.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Fornecedor inexistente")
    return f


def _padrao_json(p: PadraoPagamento | None) -> dict | None:
    if p is None:
        return None
    return {"id": p.id, "tipo": p.tipo, "janela_dias_antes": p.janela_dias_antes,
            "janela_dias_depois": p.janela_dias_depois, "tolerancia_valor": p.tolerancia_valor,
            "ajuste_max_pct": p.ajuste_max_pct, "parametros": p.parametros, "vigencia_inicio": p.vigencia_inicio,
            "vigencia_fim": p.vigencia_fim, "observacao": p.observacao}


def _fornecedor_json(f: Fornecedor, padrao: PadraoPagamento | None) -> dict:
    return {"id": f.id, "nome": f.nome, "razao_social": f.razao_social, "cnpj": f.cnpj, "categoria": f.categoria,
            "apelidos": f.apelidos, "prazo_pagamento": f.prazo_pagamento, "endereco": f.endereco,
            "observacoes": f.observacoes, "ativo": f.ativo, "padrao_vigente": _padrao_json(padrao)}


def _recorrente_json(r: DespesaRecorrente) -> dict:
    return {"id": r.id, "descricao": r.descricao, "fornecedor_id": r.fornecedor_id, "dia_inicio": r.dia_inicio,
            "dia_fim": r.dia_fim, "valor_min": r.valor_min, "valor_max": r.valor_max,
            "valor_variavel": r.valor_variavel, "vigencia_fim": r.vigencia_fim, "observacao": r.observacao,
            "ativo": r.ativo}


def _valida_recorrente(ctx: Contexto, tenant_id: int, r: DespesaRecorrente) -> None:
    if r.dia_fim < r.dia_inicio:
        raise HTTPException(status_code=422, detail="dia_fim não pode ser antes de dia_inicio")
    if r.valor_min is not None and r.valor_max is not None and r.valor_max < r.valor_min:
        raise HTTPException(status_code=422, detail="valor_max não pode ser menor que valor_min")
    if r.fornecedor_id is not None:
        _fornecedor(ctx, tenant_id, r.fornecedor_id)


# --- fornecedores ---------------------------------------------------------------------
@router.get("/tenants/{tenant_id}/fornecedores")
def listar_fornecedores(tenant_id: int, incluir_inativos: bool = False,
                        ctx: Contexto = Depends(exige_permissao("conciliacao:ler"))):
    _exigir_leitura(ctx, tenant_id)
    usar_tenant(ctx.db, tenant_id)
    q = select(Fornecedor).where(Fornecedor.tenant_id == tenant_id).order_by(Fornecedor.nome)
    if not incluir_inativos:
        q = q.where(Fornecedor.ativo.is_(True))
    fornecedores = ctx.db.scalars(q).all()
    vigentes = {p.fornecedor_id: p for p in ctx.db.scalars(
        select(PadraoPagamento).where(PadraoPagamento.tenant_id == tenant_id,
                                      PadraoPagamento.vigencia_fim.is_(None)))}
    return [_fornecedor_json(f, vigentes.get(f.id)) for f in fornecedores]


@router.post("/tenants/{tenant_id}/fornecedores", status_code=201)
def criar_fornecedor(tenant_id: int, dados: FornecedorIn, request: Request,
                     ctx: Contexto = Depends(exige_permissao("parametros:gerir"))):
    ctx.exigir("parametros:gerir", tenant_id)
    usar_tenant(ctx.db, tenant_id)
    f = Fornecedor(tenant_id=tenant_id, atualizado_por=ctx.usuario.id, ativo=True, **dados.model_dump())
    ctx.db.add(f)
    try:
        ctx.db.flush()
    except IntegrityError as e:
        ctx.db.rollback()
        raise HTTPException(status_code=409, detail="Já existe fornecedor com esse nome ou CNPJ") from e
    registrar(ctx.db, "fornecedor_criado", "fornecedor", f.id, usuario_id=ctx.usuario.id, tenant_id=tenant_id,
              detalhes={"nome": f.nome}, ip=_ip(request))
    _commit(ctx, "Já existe fornecedor com esse nome ou CNPJ")
    return _fornecedor_json(f, None)


@router.patch("/tenants/{tenant_id}/fornecedores/{fornecedor_id}")
def alterar_fornecedor(tenant_id: int, fornecedor_id: int, dados: FornecedorPatch, request: Request,
                       ctx: Contexto = Depends(exige_permissao("parametros:gerir"))):
    ctx.exigir("parametros:gerir", tenant_id)
    f = _fornecedor(ctx, tenant_id, fornecedor_id)
    mudancas = dados.model_dump(exclude_unset=True)
    for campo, valor in mudancas.items():
        setattr(f, campo, valor)
    f.atualizado_por = ctx.usuario.id
    registrar(ctx.db, "fornecedor_alterado", "fornecedor", f.id, usuario_id=ctx.usuario.id, tenant_id=tenant_id,
              detalhes={"campos": sorted(mudancas)}, ip=_ip(request))
    _commit(ctx, "Já existe fornecedor com esse nome ou CNPJ")
    vigente = ctx.db.scalar(select(PadraoPagamento).where(PadraoPagamento.fornecedor_id == f.id,
                                                         PadraoPagamento.vigencia_fim.is_(None)))
    return _fornecedor_json(f, vigente)


@router.get("/tenants/{tenant_id}/fornecedores/relatorio.xlsx")
def relatorio_crm(tenant_id: int, ctx: Contexto = Depends(exige_permissao("conciliacao:ler"))):
    """Planilha CRM_Fornecedores (2 abas) gerada na hora a partir do cadastro."""
    _exigir_leitura(ctx, tenant_id)
    usar_tenant(ctx.db, tenant_id)
    tenant = ctx.db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Cliente inexistente")
    nome = tenant.codigo.capitalize()
    return Response(gerar_relatorio_crm(ctx.db, tenant_id, nome),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="CRM_Fornecedores_{nome}.xlsx"'})


# --- padrões de pagamento ----------------------------------------------------------------
@router.get("/tenants/{tenant_id}/fornecedores/{fornecedor_id}/padroes")
def historico_padroes(tenant_id: int, fornecedor_id: int,
                      ctx: Contexto = Depends(exige_permissao("conciliacao:ler"))):
    _exigir_leitura(ctx, tenant_id)
    f = _fornecedor(ctx, tenant_id, fornecedor_id)
    return [_padrao_json(p) for p in ctx.db.scalars(
        select(PadraoPagamento).where(PadraoPagamento.fornecedor_id == f.id)
        .order_by(PadraoPagamento.vigencia_inicio.desc(), PadraoPagamento.id.desc()))]


@router.put("/tenants/{tenant_id}/fornecedores/{fornecedor_id}/padrao")
def definir_padrao(tenant_id: int, fornecedor_id: int, dados: PadraoIn, request: Request,
                   ctx: Contexto = Depends(exige_permissao("parametros:gerir"))):
    """Novo padrão vigente. O anterior é encerrado na véspera (histórico preservado);
    se começar no mesmo dia do anterior, é correção e substitui o vigente."""
    ctx.exigir("parametros:gerir", tenant_id)
    f = _fornecedor(ctx, tenant_id, fornecedor_id)
    inicio = dados.vigencia_inicio or date.today()
    # nota_mais_ajuste sem ajuste_max_pct é aceito: o match desse padrão sempre vai para humano.
    atual = ctx.db.scalar(select(PadraoPagamento).where(PadraoPagamento.fornecedor_id == f.id,
                                                       PadraoPagamento.vigencia_fim.is_(None)))
    campos = dados.model_dump(exclude={"vigencia_inicio"})
    if atual is not None and atual.vigencia_inicio > inicio:
        raise HTTPException(status_code=422, detail=(
            f"O padrão vigente começa em {atual.vigencia_inicio:%d-%m-%Y}; o novo não pode começar antes"))
    if atual is not None and atual.vigencia_inicio == inicio:
        for campo, valor in campos.items():
            setattr(atual, campo, valor)
        atual.atualizado_por = ctx.usuario.id
        novo = atual
    else:
        if atual is not None:
            atual.vigencia_fim = inicio - timedelta(days=1)
            ctx.db.flush()  # libera o índice "um vigente por fornecedor" antes do insert
        novo = PadraoPagamento(tenant_id=tenant_id, fornecedor_id=f.id, vigencia_inicio=inicio,
                               atualizado_por=ctx.usuario.id, **campos)
        ctx.db.add(novo)
    ctx.db.flush()
    registrar(ctx.db, "padrao_pagamento_definido", "fornecedor", f.id, usuario_id=ctx.usuario.id,
              tenant_id=tenant_id, detalhes={"tipo": dados.tipo, "vigencia_inicio": inicio.isoformat(),
                                             "substituiu": atual.id if atual is not None and atual is not novo
                                             else None}, ip=_ip(request))
    _commit(ctx, "Conflito ao gravar o padrão; recarregue e tente de novo")
    return _padrao_json(novo)


# --- despesas recorrentes --------------------------------------------------------------
@router.get("/tenants/{tenant_id}/despesas-recorrentes")
def listar_recorrentes(tenant_id: int, incluir_inativas: bool = False,
                       ctx: Contexto = Depends(exige_permissao("conciliacao:ler"))):
    _exigir_leitura(ctx, tenant_id)
    usar_tenant(ctx.db, tenant_id)
    q = select(DespesaRecorrente).where(DespesaRecorrente.tenant_id == tenant_id)
    if not incluir_inativas:
        q = q.where(DespesaRecorrente.ativo.is_(True))
    return [_recorrente_json(r) for r in ctx.db.scalars(
        q.order_by(DespesaRecorrente.dia_inicio, DespesaRecorrente.descricao))]


@router.post("/tenants/{tenant_id}/despesas-recorrentes", status_code=201)
def criar_recorrente(tenant_id: int, dados: RecorrenteIn, request: Request,
                     ctx: Contexto = Depends(exige_permissao("parametros:gerir"))):
    ctx.exigir("parametros:gerir", tenant_id)
    usar_tenant(ctx.db, tenant_id)
    r = DespesaRecorrente(tenant_id=tenant_id, atualizado_por=ctx.usuario.id, ativo=True, **dados.model_dump())
    _valida_recorrente(ctx, tenant_id, r)
    ctx.db.add(r)
    try:
        ctx.db.flush()
    except IntegrityError as e:
        ctx.db.rollback()
        raise HTTPException(status_code=409, detail="Já existe despesa recorrente com essa descrição") from e
    registrar(ctx.db, "recorrente_criada", "despesa_recorrente", r.id, usuario_id=ctx.usuario.id,
              tenant_id=tenant_id, detalhes={"descricao": r.descricao}, ip=_ip(request))
    _commit(ctx, "Já existe despesa recorrente com essa descrição")
    return _recorrente_json(r)


@router.patch("/tenants/{tenant_id}/despesas-recorrentes/{recorrente_id}")
def alterar_recorrente(tenant_id: int, recorrente_id: int, dados: RecorrentePatch, request: Request,
                       ctx: Contexto = Depends(exige_permissao("parametros:gerir"))):
    ctx.exigir("parametros:gerir", tenant_id)
    usar_tenant(ctx.db, tenant_id)
    r = ctx.db.get(DespesaRecorrente, recorrente_id)
    if r is None or r.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Despesa recorrente inexistente")
    mudancas = dados.model_dump(exclude_unset=True)
    for campo, valor in mudancas.items():
        setattr(r, campo, valor)
    _valida_recorrente(ctx, tenant_id, r)
    r.atualizado_por = ctx.usuario.id
    registrar(ctx.db, "recorrente_alterada", "despesa_recorrente", r.id, usuario_id=ctx.usuario.id,
              tenant_id=tenant_id, detalhes={"campos": sorted(mudancas)}, ip=_ip(request))
    _commit(ctx, "Já existe despesa recorrente com essa descrição")
    return _recorrente_json(r)
