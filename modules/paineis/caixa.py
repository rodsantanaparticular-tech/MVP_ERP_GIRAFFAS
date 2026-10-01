"""Visão CAIXA do painel de fornecedores: o que saiu do banco em cada mês, pelas categorias do DRE.

Regras:
- Mês = data do lançamento no extrato (quando o dinheiro saiu ou entrou), somando todas as contas do cliente.
- Categoria = classe do lançamento → `extrato_categorias` (a exceção por favorecido vale antes da regra geral).
  Lançamento sem classe (o texto não decide, ex.: Pix de funcionário = FOLHA, ADIANTAMENTO ou DOBRA) usa as
  classes que a planilha já deu para aquele texto: se todas caem na mesma categoria, vale ela; senão
  "A CLASSIFICAR". Sem favorecido também é "A CLASSIFICAR", identificado pelo texto do banco.
- Despesa = saídas (entrada no grupo despesa, ex.: estorno, abate). Receita = entradas do grupo 'receita'
  (vendas recebidas no banco). Fora do DRE (transferência entre contas, aporte, retirada) e outras entradas
  (rendimentos) aparecem à parte e não entram no total de despesas.
- Fornecedor = cadastro do CRM quando o favorecido está ligado a ele; senão, o favorecido.
"""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modules.banco.classificacao import chave
from modules.banco.models import ExtratoCategoria, ExtratoLancamento, ExtratoRegra
from modules.pagamentos.models import Fornecedor, PadraoPagamento
from modules.paineis.fornecedores import MES_INICIAL

A_CLASSIFICAR = "A CLASSIFICAR"
_MES = func.to_char(ExtratoLancamento.data, "YYYY-MM")


def meses_disponiveis(db: Session, tenant_id: int) -> list[str]:
    return [m for (m,) in db.execute(select(_MES).where(ExtratoLancamento.tenant_id == tenant_id,
                                                        _MES >= MES_INICIAL).distinct().order_by(_MES))]


def _categoria(l: ExtratoLancamento, regras: dict[int, ExtratoRegra],
               cats: dict[tuple, tuple[str, str]]) -> tuple[str, str]:
    def de(cls):
        return cats.get((l.natureza, cls, l.favorecido)) or cats.get((l.natureza, cls, None))

    if l.classificacao:
        achou = de(l.classificacao)
    elif l.regra_id in regras and regras[l.regra_id].classificacoes:
        opcoes = {de(c) for c in regras[l.regra_id].classificacoes}
        achou = opcoes.pop() if len(opcoes) == 1 else None
    else:
        achou = None
    return achou or (A_CLASSIFICAR, "despesa" if l.natureza == "D" else "outra_entrada")


def _bloco(valores: dict[str, dict[str, Decimal]], meses: list[str]) -> list[dict]:
    saida = [{"categoria": c, "valores": {m: v.get(m, Decimal(0)) for m in meses}, "total": sum(v.values(), Decimal(0))}
             for c, v in valores.items()]
    return sorted(saida, key=lambda b: -abs(b["total"]))


def montar(db: Session, tenant_id: int, meses: list[str]) -> dict:
    fornecedores = {f.id: f for f in db.scalars(select(Fornecedor).where(Fornecedor.tenant_id == tenant_id))}
    padroes = {p.fornecedor_id: p.tipo for p in db.scalars(select(PadraoPagamento).where(
        PadraoPagamento.tenant_id == tenant_id, PadraoPagamento.vigencia_fim.is_(None)))}
    regras = {r.id: r for r in db.scalars(select(ExtratoRegra).where(ExtratoRegra.tenant_id == tenant_id))}
    cats = {(c.natureza, c.classificacao, c.favorecido): (c.categoria, c.grupo)
            for c in db.scalars(select(ExtratoCategoria).where(ExtratoCategoria.tenant_id == tenant_id))}

    zero = lambda: {m: Decimal(0) for m in meses}  # noqa: E731
    receita, total = zero(), zero()
    valores: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    info: dict[tuple[str, str], dict] = {}
    lancs: dict[tuple[str, str], int] = defaultdict(int)
    fora: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    outras: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    ate = None
    for l in db.scalars(select(ExtratoLancamento).where(ExtratoLancamento.tenant_id == tenant_id, _MES.in_(meses))):
        m = f"{l.data:%Y-%m}"
        ate = max(ate, l.data) if ate else l.data
        categoria, grupo = _categoria(l, regras, cats)
        if grupo == "receita":
            receita[m] += l.valor
        elif grupo == "fora_dre":
            fora[categoria][m] += l.valor
        elif grupo == "outra_entrada":
            outras[categoria if l.favorecido else f"{categoria} — {chave(l.historico)}"][m] += l.valor
        else:
            crm = fornecedores.get(l.fornecedor_id)
            nome = crm.nome if crm else l.favorecido or f"? {chave(l.historico)}"
            k = (categoria, nome)
            valores[k][m] -= l.valor               # saída (valor < 0) vira despesa positiva
            total[m] -= l.valor
            lancs[k] += 1
            info[k] = {"crm_id": crm.id if crm else None, "padrao": padroes.get(crm.id) if crm else None,
                       "escritorio": False, "sem_favorecido": l.favorecido is None}

    linhas, categorias = [], defaultdict(zero)
    for (categoria, nome), por_mes in valores.items():
        v = {m: por_mes.get(m, Decimal(0)) for m in meses}
        for m in meses:
            categorias[categoria][m] += v[m]
        linhas.append({"categoria": categoria, "fornecedor": nome, "valores": v, "total": sum(v.values(), Decimal(0)),
                       "documentos": lancs[(categoria, nome)], **info[(categoria, nome)]})
    linhas.sort(key=lambda l: (-sum(categorias[l["categoria"]].values()), l["categoria"], -l["total"]))
    return {
        "visao": "caixa",
        "meses": meses,
        "receita": receita,
        "total_despesas": total,
        "categorias": [{"categoria": c, "valores": v, "total": sum(v.values(), Decimal(0))}
                       for c, v in sorted(categorias.items(), key=lambda kv: (kv[0] == A_CLASSIFICAR,
                                                                              -sum(kv[1].values())))],
        "linhas": linhas,
        "fora_dre": _bloco(fora, meses),
        "outras_entradas": _bloco(outras, meses),
        "extrato_ate": ate,
    }
