"""Motor de match banco × GCOM (passo 5c-3): cada saída do extrato ↔ documento(s) do GCOM que ela pagou.

Função pura (sem banco de dados): recebe débitos, documentos e o padrão de pagamento de cada fornecedor e
devolve as conciliações. Quem grava é `modules/conciliacao/servico.py`.

Regras (padrões do CRM, `padroes_pagamento.tipo`):
- um_para_um (RFG): 1 débito = 1 documento.
- agrupado_vencimento (Ribeiro): 1 débito = soma dos documentos com o mesmo vencimento.
- nota_mais_ajuste (JM): 1 débito = nota principal + nota complementar com o MESMO número (sufixo "1" ou "/1",
  ou prefixo "D"). Agrupa pelo NÚMERO, não pelo vencimento (o complemento às vezes vem com outro vencimento).
  Pago depois do vencimento, aceita acréscimo de até `parametros.atraso_max_pct` (padrão 5%) como multa/juros,
  separado no campo `acrescimo`.
- consolidado_mensal (Kelminas): 1 débito no mês seguinte (por volta de `parametros.dia_debito`, padrão 5)
  = soma dos documentos do mês (competência). Sem soma exata e com 1 só débito na janela → "investigar" com a
  diferença à mostra.
- livre, sem padrão ou sem fornecedor: só valor exato + janela de data, e só se o par for único dos dois lados
  → "sugerido" (um humano confirma). Nunca "batido".

Janela: o débito pode sair `janela_dias_antes` antes até `janela_dias_depois` depois do vencimento (data de
referência do grupo). Empate (um débito servindo a 2 grupos, ou um grupo servindo a 2 débitos) → "investigar",
nunca escolha automática. Todo valor é Decimal (centavo exato).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal("0.00")
BATIDO, SUGERIDO, INVESTIGAR = "batido", "sugerido", "investigar"


@dataclass(frozen=True)
class Debito:
    id: int
    data: date
    valor: Decimal               # positivo (o que saiu)
    fornecedor_id: int | None


@dataclass(frozen=True)
class Documento:
    id: int
    numero: str
    valor: Decimal
    venc: date
    mes: str                     # competência no DRE (AAAA-MM)
    fornecedor_id: int | None


@dataclass(frozen=True)
class Padrao:
    tipo: str
    id: int | None = None
    janela_dias_antes: int = 3
    janela_dias_depois: int = 5
    tolerancia_valor: Decimal = ZERO
    parametros: dict = field(default_factory=dict)


@dataclass
class Resultado:
    status: str
    regra: str
    debitos: list[Debito]
    documentos: list[Documento]
    padrao_id: int | None = None
    acrescimo: Decimal = ZERO    # multa/juros por atraso (só nota_mais_ajuste)
    nota: str = ""

    @property
    def total_extrato(self) -> Decimal:
        return sum((d.valor for d in self.debitos), ZERO)

    @property
    def total_documentos(self) -> Decimal:
        return sum((d.valor for d in self.documentos), ZERO)

    @property
    def diferenca(self) -> Decimal:
        return self.total_extrato - self.total_documentos

    @property
    def competencia(self) -> str:
        if self.documentos:
            return min(d.mes for d in self.documentos)
        return min(d.data for d in self.debitos).strftime("%Y-%m")


@dataclass
class _Grupo:
    chave: str
    docs: list[Documento]
    ref: date                    # data de referência para a janela

    @property
    def total(self) -> Decimal:
        return sum((d.valor for d in self.docs), ZERO)


def _num(numero: str) -> str:
    return re.sub(r"\s+", "", numero or "").upper()


def numero_base(numero: str, existentes: set[str]) -> str:
    """Número da nota principal: '2313501' → '231350' se '231350' existe; '231350/1' → '231350'; 'D231350' → '231350'."""
    n = _num(numero)
    if n.endswith("/1"):
        return n[:-2]
    if n.startswith("D") and n[1:] in existentes:
        return n[1:]
    if n.endswith("1") and n[:-1] in existentes:
        return n[:-1]
    return n


def _grupos(padrao: Padrao, docs: list[Documento]) -> list[_Grupo]:
    if padrao.tipo == "agrupado_vencimento":
        por: dict[date, list[Documento]] = defaultdict(list)
        for d in docs:
            por[d.venc].append(d)
        return [_Grupo(f"venc:{v.isoformat()}", g, v) for v, g in por.items()]
    if padrao.tipo == "nota_mais_ajuste":
        existentes = {_num(d.numero) for d in docs}
        por_num: dict[str, list[Documento]] = defaultdict(list)
        for d in docs:
            por_num[numero_base(d.numero, existentes)].append(d)
        grupos = []
        for base, g in por_num.items():
            principal = [d for d in g if _num(d.numero) == base]
            grupos.append(_Grupo(f"nota:{base}", g, min(d.venc for d in (principal or g))))
        return grupos
    if padrao.tipo == "consolidado_mensal":
        dia = int(padrao.parametros.get("dia_debito", 5))
        por_mes: dict[str, list[Documento]] = defaultdict(list)
        for d in docs:
            por_mes[d.mes].append(d)
        grupos = []
        for mes, g in por_mes.items():
            a, m = int(mes[:4]), int(mes[5:7])
            seguinte = date(a + (m == 12), m % 12 + 1, 1)
            grupos.append(_Grupo(f"mes:{mes}", g, seguinte + timedelta(days=dia - 1)))
        return grupos
    return [_Grupo(f"doc:{d.id}", [d], d.venc) for d in docs]


def _na_janela(deb: Debito, ref: date, padrao: Padrao) -> bool:
    return ref - timedelta(days=padrao.janela_dias_antes) <= deb.data <= ref + timedelta(days=padrao.janela_dias_depois)


def _acrescimo_aceito(deb: Debito, g: _Grupo, padrao: Padrao) -> Decimal | None:
    """nota_mais_ajuste pago após o vencimento: diferença positiva até atraso_max_pct vira multa/juros."""
    if padrao.tipo != "nota_mais_ajuste" or deb.data <= g.ref:
        return None
    dif = deb.valor - g.total
    teto = (g.total * Decimal(str(padrao.parametros.get("atraso_max_pct", "0.05")))).quantize(Decimal("0.01"))
    return dif if ZERO < dif <= teto else None


def _pareia(debitos: list[Debito], grupos: list[_Grupo], padrao: Padrao, status_ok: str,
            regra: str) -> tuple[list[Resultado], set[int], set[int]]:
    """Pares únicos dos dois lados (débito ↔ grupo). Devolve resultados, débitos e documentos usados."""
    cand: dict[int, list[tuple[int, Decimal]]] = defaultdict(list)   # débito → [(grupo, acréscimo)]
    por_grupo: dict[int, list[int]] = defaultdict(list)
    for di, deb in enumerate(debitos):
        for gi, g in enumerate(grupos):
            if not _na_janela(deb, g.ref, padrao):
                continue
            if abs(deb.valor - g.total) <= padrao.tolerancia_valor:
                acr = ZERO
            else:
                acr = _acrescimo_aceito(deb, g, padrao)
                if acr is None:
                    continue
            cand[di].append((gi, acr))
            por_grupo[gi].append(di)

    resultados, deb_usados, doc_usados = [], set(), set()
    ambiguos: set[int] = set()
    for di, opcoes in cand.items():
        if len(opcoes) == 1 and len(por_grupo[opcoes[0][0]]) == 1:
            gi, acr = opcoes[0]
            g = grupos[gi]
            nota = f"acréscimo por atraso R$ {acr}" if acr else ""
            resultados.append(Resultado(status_ok, regra, [debitos[di]], list(g.docs), padrao.id, acr, nota))
            deb_usados.add(debitos[di].id)
            doc_usados.update(d.id for d in g.docs)
        else:
            ambiguos.add(di)
    for di in sorted(ambiguos):
        docs = [d for gi, _ in cand[di] for d in grupos[gi].docs if d.id not in doc_usados]
        if not docs:
            continue
        resultados.append(Resultado(INVESTIGAR, f"{regra}:empate", [debitos[di]], docs, padrao.id,
                                    nota=f"{len(cand[di])} candidatos com o mesmo valor; decisão humana"))
        deb_usados.add(debitos[di].id)
    return resultados, deb_usados, doc_usados


def conciliar(debitos: list[Debito], documentos: list[Documento],
              padroes: dict[int, Padrao]) -> list[Resultado]:
    """Concilia por fornecedor com padrão; o resto passa pelo match exato e único (sugerido)."""
    resultados: list[Resultado] = []
    deb_livres = {d.id: d for d in debitos}
    doc_livres = {d.id: d for d in documentos}

    for fid, padrao in sorted(padroes.items()):
        if padrao.tipo == "livre":
            continue
        debs = [d for d in deb_livres.values() if d.fornecedor_id == fid]
        docs = [d for d in doc_livres.values() if d.fornecedor_id == fid]
        if not debs or not docs:
            continue
        grupos = _grupos(padrao, docs)
        res, du, ou = _pareia(debs, grupos, padrao, BATIDO, padrao.tipo)
        resultados += res
        for i in du:
            deb_livres.pop(i, None)
        for i in ou:
            doc_livres.pop(i, None)

        if padrao.tipo == "consolidado_mensal":   # divergência visível: 1 débito ↔ 1 mês, valor diferente
            for g in _grupos(padrao, [d for d in doc_livres.values() if d.fornecedor_id == fid]):
                na_janela = [d for d in deb_livres.values() if d.fornecedor_id == fid and _na_janela(d, g.ref, padrao)]
                if len(na_janela) == 1:
                    r = Resultado(INVESTIGAR, "consolidado_mensal:divergente", na_janela, list(g.docs), padrao.id)
                    r.nota = f"débito difere da soma das notas do mês em R$ {r.diferenca}"
                    resultados.append(r)
                    deb_livres.pop(na_janela[0].id)
                    for d in g.docs:
                        doc_livres.pop(d.id)

    # Fallback: valor exato + janela padrão, par único dos dois lados → sugerido.
    padrao_fb = Padrao("um_para_um")
    sobra_deb = sorted(deb_livres.values(), key=lambda d: (d.data, d.id))
    sobra_doc = list(doc_livres.values())
    cand: dict[int, list[Documento]] = defaultdict(list)
    por_doc: dict[int, list[Debito]] = defaultdict(list)
    for deb in sobra_deb:
        for doc in sobra_doc:
            mesmo_forn = deb.fornecedor_id is None or doc.fornecedor_id is None or deb.fornecedor_id == doc.fornecedor_id
            if mesmo_forn and deb.valor == doc.valor and _na_janela(deb, doc.venc, padrao_fb):
                cand[deb.id].append(doc)
                por_doc[doc.id].append(deb)
    for deb in sobra_deb:
        docs = cand.get(deb.id, [])
        if len(docs) == 1 and len(por_doc[docs[0].id]) == 1:
            p = padroes.get(deb.fornecedor_id) if deb.fornecedor_id else None
            resultados.append(Resultado(SUGERIDO, "valor_exato_unico", [deb], docs, p.id if p else None,
                                        nota="valor e data batem; confirmar"))
    return resultados
