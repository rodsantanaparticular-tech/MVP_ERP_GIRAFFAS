"""Banco: contas, resumo mensal (entradas, saídas, saldo) e lançamentos. Exige `banco:ler` no cliente."""
import re
from collections import defaultdict
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from core.db import usar_tenant
from core.security.rbac import Contexto, exige_permissao
from modules.banco.models import ContaBancaria, ExtratoImportacao, ExtratoLancamento
from modules.banco.servico import resumo_mensal
from modules.paineis.router import PAGINAS

router = APIRouter(tags=["banco e caixa"])
_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def tipo_lancamento(historico: str) -> str:
    """Agrupa o histórico ignorando CPF/CNPJ, documentos e datas: 'PIX RECEBIDO 14349745610' → 'PIX RECEBIDO'."""
    texto = re.sub(r"\d[\d./-]*", " ", historico.upper())
    palavras = [p for p in re.split(r"\s+", texto) if p and p not in {"-", ".", "/"}]
    return " ".join(palavras[:4]) or "(sem histórico)"


def _contas(ctx: Contexto, tenant_id: int, conta_id: int | None = None) -> list[ContaBancaria]:
    ctx.exigir("banco:ler", tenant_id)
    usar_tenant(ctx.db, tenant_id)
    q = select(ContaBancaria).where(ContaBancaria.tenant_id == tenant_id).order_by(ContaBancaria.id)
    if conta_id is not None:
        q = q.where(ContaBancaria.id == conta_id)
    contas = ctx.db.scalars(q).all()
    if conta_id is not None and not contas:
        raise HTTPException(status_code=404, detail="Conta inexistente")
    return contas


@router.get("/tenants/{tenant_id}/banco/contas")
def listar_contas(tenant_id: int, ctx: Contexto = Depends(exige_permissao("banco:ler"))):
    saida = []
    for c in _contas(ctx, tenant_id):
        de, ate, n = ctx.db.execute(select(func.min(ExtratoLancamento.data), func.max(ExtratoLancamento.data),
                                           func.count()).where(ExtratoLancamento.conta_id == c.id)).one()
        ultima = ctx.db.scalar(select(func.max(ExtratoImportacao.importado_em))
                               .where(ExtratoImportacao.conta_id == c.id))
        saida.append({"id": c.id, "banco": c.banco, "apelido": c.apelido, "agencia": c.agencia,
                      "de": de, "ate": ate, "lancamentos": n, "ultima_importacao": ultima})
    return saida


@router.get("/tenants/{tenant_id}/banco/resumo")
def resumo(tenant_id: int, de: str = "2025-11", ate: str = "2099-12",
           ctx: Contexto = Depends(exige_permissao("banco:ler"))):
    if not (_MES.match(de) and _MES.match(ate)) or de > ate:
        raise HTTPException(status_code=422, detail="Use de/ate no formato AAAA-MM (de ≤ ate)")
    return list(resumo_mensal(ctx.db, _contas(ctx, tenant_id), de, ate).values())


@router.get("/tenants/{tenant_id}/banco/lancamentos")
def lancamentos(tenant_id: int, mes: str, conta_id: int | None = None,
                tipo: Literal["todos", "entradas", "saidas"] = "todos", busca: str | None = Query(None, max_length=80),
                ctx: Contexto = Depends(exige_permissao("banco:ler"))):
    if not _MES.match(mes):
        raise HTTPException(status_code=422, detail="Use mes no formato AAAA-MM")
    contas = {c.id: c for c in _contas(ctx, tenant_id, conta_id)}
    ano, m = int(mes[:4]), int(mes[5:])
    q = (select(ExtratoLancamento).where(ExtratoLancamento.conta_id.in_(contas),
                                         func.extract("year", ExtratoLancamento.data) == ano,
                                         func.extract("month", ExtratoLancamento.data) == m)
         .order_by(ExtratoLancamento.data, ExtratoLancamento.conta_id, ExtratoLancamento.ordem))
    if tipo == "entradas":
        q = q.where(ExtratoLancamento.valor > 0)
    elif tipo == "saidas":
        q = q.where(ExtratoLancamento.valor < 0)
    if busca:
        q = q.where(ExtratoLancamento.historico.ilike(f"%{busca}%"))
    linhas = ctx.db.scalars(q).all()
    grupos: dict[tuple[str, str], dict] = defaultdict(lambda: {"valor": Decimal(0), "quantidade": 0})
    for l in linhas:
        g = grupos[("entrada" if l.valor > 0 else "saida", tipo_lancamento(l.historico))]
        g["valor"] += l.valor
        g["quantidade"] += 1
    return {
        "mes": mes,
        "grupos": sorted(({"natureza": k[0], "tipo": k[1], **v} for k, v in grupos.items()),
                         key=lambda g: -abs(g["valor"])),
        "lancamentos": [{"data": l.data, "conta": contas[l.conta_id].apelido, "historico": l.historico,
                         "documento": l.documento, "valor": l.valor, "saldo": l.saldo_informado,
                         "favorecido": l.favorecido, "classificacao": l.classificacao,
                         "classificacao_origem": l.classificacao_origem}
                        for l in linhas[:3000]],
        "total_linhas": len(linhas),
    }


@router.get("/painel/banco", include_in_schema=False)
def pagina_banco():
    return FileResponse(PAGINAS / "painel_banco.html", media_type="text/html")
