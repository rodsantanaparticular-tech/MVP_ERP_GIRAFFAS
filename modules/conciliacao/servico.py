"""Roda o motor sobre o banco do cliente e grava as conciliações; resumo e lista para a API.

Regras de gravação:
- Cada rodada refaz só o que o motor criou e ninguém confirmou (`criado_por = 'motor'`, `confirmado_por` NULL).
  O que um humano criou ou confirmou fica, e os débitos/documentos dele saem do motor.
- Débito = saída do extrato (natureza D) a partir de MES_INICIAL, exceto transferência entre contas próprias.
- Documento = despesa do GCOM (Raio-X) das lojas do cliente, exceto PREVISTO (previsão não é pagamento).
- Fornecedor do documento = cadastro do CRM pelos apelidos (mesma regra do painel de fornecedores).
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from modules.banco.classificacao import TRANSFERENCIA
from modules.banco.models import ExtratoLancamento
from modules.conciliacao.models import Conciliacao, ConciliacaoItem
from modules.conciliacao.motor import Debito, Documento, Padrao, conciliar
from modules.pagamentos.models import Fornecedor, PadraoPagamento
from modules.paineis.fornecedores import MES_INICIAL
from modules.raiox_dre.models import Despesa
from modules.raiox_dre.ponte import normalizar
from modules.tenants.models import Loja

INICIO = date(int(MES_INICIAL[:4]), int(MES_INICIAL[5:]), 1)
ZERO = Decimal("0.00")


def _lojas(db: Session, tenant_id: int) -> list[int]:
    return list(db.scalars(select(Loja.id).where(Loja.tenant_id == tenant_id)))


def _ocupados(db: Session, tenant_id: int) -> tuple[set[int], set[int]]:
    """Débitos e documentos presos em conciliação ativa (inclusive as que o motor vai refazer, se chamadas antes)."""
    linhas = db.execute(select(ConciliacaoItem.extrato_lancamento_id, ConciliacaoItem.despesa_id)
                        .where(ConciliacaoItem.tenant_id == tenant_id, ConciliacaoItem.ativo.is_(True))).all()
    return {e for e, _ in linhas if e}, {d for _, d in linhas if d}


def _debitos_query(tenant_id: int):
    return select(ExtratoLancamento).where(
        ExtratoLancamento.tenant_id == tenant_id, ExtratoLancamento.natureza == "D",
        ExtratoLancamento.data >= INICIO,
        func.coalesce(ExtratoLancamento.classificacao, "") != TRANSFERENCIA)


def _documentos_query(lojas: list[int]):
    return select(Despesa).where(Despesa.loja_id.in_(lojas), Despesa.mes >= MES_INICIAL,
                                 Despesa.status_gcom != "PREVISTO")


def rodar(db: Session, tenant_id: int) -> dict:
    """Refaz as conciliações do motor. Quem chama faz o commit (ou rollback, na simulação)."""
    refazer = select(Conciliacao.id).where(Conciliacao.tenant_id == tenant_id, Conciliacao.criado_por == "motor",
                                           Conciliacao.confirmado_por.is_(None))
    db.execute(delete(Conciliacao).where(Conciliacao.id.in_(refazer)))
    db.flush()
    deb_ocup, doc_ocup = _ocupados(db, tenant_id)

    por_apelido = {normalizar(a): f.id for f in db.scalars(select(Fornecedor).where(Fornecedor.tenant_id == tenant_id))
                   for a in f.apelidos}
    padroes = {p.fornecedor_id: Padrao(p.tipo, p.id, p.janela_dias_antes, p.janela_dias_depois,
                                       Decimal(p.tolerancia_valor), p.parametros or {})
               for p in db.scalars(select(PadraoPagamento).where(PadraoPagamento.tenant_id == tenant_id,
                                                                 PadraoPagamento.vigencia_fim.is_(None)))}
    debitos = [Debito(l.id, l.data, -Decimal(l.valor), l.fornecedor_id)
               for l in db.scalars(_debitos_query(tenant_id)) if l.id not in deb_ocup]
    documentos = [Documento(d.id, d.doc, Decimal(d.valor).quantize(Decimal("0.01")), d.venc, d.mes,
                            por_apelido.get(normalizar(d.fornecedor)))
                  for d in db.scalars(_documentos_query(_lojas(db, tenant_id))) if d.id not in doc_ocup]

    contagem: dict[str, int] = defaultdict(int)
    for r in conciliar(debitos, documentos, padroes):
        c = Conciliacao(tenant_id=tenant_id, competencia=r.competencia, status=r.status, padrao_id=r.padrao_id,
                        regra_aplicada=r.regra, total_extrato=r.total_extrato, total_despesas=r.total_documentos,
                        acrescimo=r.acrescimo, nota=r.nota or None, criado_por="motor")
        db.add(c)
        db.flush()
        for d in r.debitos:
            db.add(ConciliacaoItem(tenant_id=tenant_id, conciliacao_id=c.id, tipo="extrato",
                                   extrato_lancamento_id=d.id, valor_alocado=d.valor))
        for d in r.documentos:
            db.add(ConciliacaoItem(tenant_id=tenant_id, conciliacao_id=c.id, tipo="despesa",
                                   despesa_id=d.id, valor_alocado=d.valor))
        contagem[r.status] += 1
    db.flush()
    return {"debitos_avaliados": len(debitos), "documentos_avaliados": len(documentos), **contagem}


def resumo(db: Session, tenant_id: int) -> list[dict]:
    """Por mês: conciliações por status (quantidade e valor) + o que sobrou sem par dos dois lados."""
    meses: dict[str, dict] = defaultdict(lambda: {"status": {}, "sem_documento": {"qtd": 0, "valor": ZERO},
                                                  "sem_pagamento": {"qtd": 0, "valor": ZERO}})
    for comp, status, n, ext, desp, acr in db.execute(
            select(Conciliacao.competencia, Conciliacao.status, func.count(), func.sum(Conciliacao.total_extrato),
                   func.sum(Conciliacao.total_despesas), func.sum(Conciliacao.acrescimo))
            .where(Conciliacao.tenant_id == tenant_id).group_by(Conciliacao.competencia, Conciliacao.status)):
        meses[comp]["status"][status] = {"qtd": n, "extrato": ext, "documentos": desp, "acrescimo": acr}

    deb_ocup, doc_ocup = _ocupados(db, tenant_id)
    for l in db.scalars(_debitos_query(tenant_id)):
        if l.id not in deb_ocup:
            m = meses[l.data.strftime("%Y-%m")]["sem_documento"]
            m["qtd"] += 1
            m["valor"] += -Decimal(l.valor)
    for d in db.scalars(_documentos_query(_lojas(db, tenant_id))):
        if d.id not in doc_ocup:
            m = meses[d.mes]["sem_pagamento"]
            m["qtd"] += 1
            m["valor"] += Decimal(d.valor).quantize(Decimal("0.01"))
    return [{"mes": m, **v} for m, v in sorted(meses.items())]


def listar(db: Session, tenant_id: int, status: str | None = None, mes: str | None = None) -> list[dict]:
    q = select(Conciliacao).where(Conciliacao.tenant_id == tenant_id)
    if status:
        q = q.where(Conciliacao.status == status)
    if mes:
        q = q.where(Conciliacao.competencia == mes)
    concs = db.scalars(q.order_by(Conciliacao.competencia, Conciliacao.id)).all()
    if not concs:
        return []
    itens = db.scalars(select(ConciliacaoItem).where(ConciliacaoItem.conciliacao_id.in_([c.id for c in concs]))).all()
    lanc = {l.id: l for l in db.scalars(select(ExtratoLancamento).where(
        ExtratoLancamento.id.in_([i.extrato_lancamento_id for i in itens if i.extrato_lancamento_id])))}
    desp = {d.id: d for d in db.scalars(select(Despesa).where(
        Despesa.id.in_([i.despesa_id for i in itens if i.despesa_id])))}
    por_conc: dict[int, list] = defaultdict(list)
    for i in itens:
        por_conc[i.conciliacao_id].append(i)
    saida = []
    for c in concs:
        extrato, documentos = [], []
        for i in por_conc[c.id]:
            if i.extrato_lancamento_id:
                l = lanc[i.extrato_lancamento_id]
                extrato.append({"id": l.id, "data": l.data, "historico": l.historico, "favorecido": l.favorecido,
                                "valor": i.valor_alocado})
            else:
                d = desp[i.despesa_id]
                documentos.append({"id": d.id, "doc": d.doc, "fornecedor": d.fornecedor, "venc": d.venc,
                                   "categoria": d.desembolso, "valor": i.valor_alocado})
        saida.append({"id": c.id, "competencia": c.competencia, "status": c.status, "regra": c.regra_aplicada,
                      "total_extrato": c.total_extrato, "total_documentos": c.total_despesas,
                      "diferenca": c.diferenca, "acrescimo": c.acrescimo, "nota": c.nota,
                      "extrato": extrato, "documentos": documentos})
    return saida
