"""Peso de cada fornecedor: valor por mês, por categoria do DRE, contra despesa total e receita.

Regras:
- Visão COMPETÊNCIA = mês da despesa no DRE (Raio-X: mês da data de entrada do documento).
- Categoria = "Tipo de Desembolso" do GCOM. Documento rateado entre categorias (sub_itens) entra
  em cada categoria com o valor da sua linha.
- Fornecedor = cadastro do CRM quando o nome do GCOM está nos apelidos; senão, o nome do GCOM.
- "O PRÓPRIO ESCRITÓRIO" não é fornecedor: aparece como "O Próprio Escritório — <sub-tipo>".
- Receita = faturamento diário (vendas_realizado_dia) somado no mês.
Os percentuais (sobre total, categoria ou receita) são divisões diretas destes valores.
"""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modules.pagamentos.models import Fornecedor, PadraoPagamento
from modules.raiox_dre.models import Despesa
from modules.raiox_dre.ponte import normalizar
from modules.vendas.models import RealizadoDia

ESCRITORIO = "O PRÓPRIO ESCRITÓRIO"
MES_INICIAL = "2026-02"      # faturamento no GCOM começa em 02/02/2026 (decisão do usuário, 29/09)


def meses_disponiveis(db: Session, lojas: list[int]) -> list[str]:
    """Meses com despesas (o painel é sobre despesas; mês só com receita ainda está incompleto)."""
    desp = {m for (m,) in db.execute(select(Despesa.mes).where(Despesa.loja_id.in_(lojas)).distinct())}
    return sorted(m for m in desp if m >= MES_INICIAL)


def _itens(d: Despesa) -> list[tuple[str, str, Decimal]]:
    """(categoria, sub-tipo, valor) de cada linha do documento."""
    if isinstance(d.sub_itens, list) and d.sub_itens:
        return [(i.get("tipo") or d.desembolso, i.get("sub") or d.sub, Decimal(str(i.get("valor") or 0)))
                for i in d.sub_itens]
    return [(d.desembolso, d.sub, Decimal(d.valor))]


def montar(db: Session, tenant_id: int, lojas: list[int], meses: list[str]) -> dict:
    fornecedores = db.scalars(select(Fornecedor).where(Fornecedor.tenant_id == tenant_id)).all()
    padroes = {p.fornecedor_id: p.tipo for p in db.scalars(select(PadraoPagamento).where(
        PadraoPagamento.tenant_id == tenant_id, PadraoPagamento.vigencia_fim.is_(None)))}
    por_apelido = {normalizar(a): f for f in fornecedores for a in f.apelidos}

    valores: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    info: dict[tuple[str, str], dict] = {}
    docs: dict[tuple[str, str], set] = defaultdict(set)
    for d in db.scalars(select(Despesa).where(Despesa.loja_id.in_(lojas), Despesa.mes.in_(meses))):
        crm = por_apelido.get(normalizar(d.fornecedor))
        for categoria, sub, valor in _itens(d):
            if normalizar(d.fornecedor) == normalizar(ESCRITORIO):
                nome, crm_id, padrao = f"O Próprio Escritório — {sub.title()}", None, None
            elif crm is not None:
                nome, crm_id, padrao = crm.nome, crm.id, padroes.get(crm.id)
            else:
                nome, crm_id, padrao = d.fornecedor, None, None
            chave = (categoria, nome)
            valores[chave][d.mes] += valor
            docs[chave].add(d.id)
            info[chave] = {"crm_id": crm_id, "padrao": padrao, "escritorio": crm_id is None and
                           normalizar(d.fornecedor) == normalizar(ESCRITORIO)}

    receita = {m: Decimal(0) for m in meses}
    mes_da_venda = func.to_char(RealizadoDia.data, "YYYY-MM")
    for m, v in db.execute(select(mes_da_venda, func.sum(RealizadoDia.faturamento))
                           .where(RealizadoDia.loja_id.in_(lojas), mes_da_venda.in_(meses))
                           .group_by(mes_da_venda)):
        receita[m] = v

    linhas = []
    categorias: dict[str, dict[str, Decimal]] = defaultdict(lambda: {m: Decimal(0) for m in meses})
    total = {m: Decimal(0) for m in meses}
    for (categoria, nome), por_mes in valores.items():
        v = {m: por_mes.get(m, Decimal(0)) for m in meses}
        for m in meses:
            categorias[categoria][m] += v[m]
            total[m] += v[m]
        linhas.append({"categoria": categoria, "fornecedor": nome, "valores": v,
                       "total": sum(v.values(), Decimal(0)), "documentos": len(docs[(categoria, nome)]),
                       **info[(categoria, nome)]})
    linhas.sort(key=lambda l: (-sum(categorias[l["categoria"]].values()), l["categoria"], -l["total"]))
    return {
        "visao": "competencia",
        "meses": meses,
        "receita": receita,
        "total_despesas": total,
        "categorias": [{"categoria": c, "valores": v, "total": sum(v.values(), Decimal(0))}
                       for c, v in sorted(categorias.items(), key=lambda kv: -sum(kv[1].values()))],
        "linhas": linhas,
    }
