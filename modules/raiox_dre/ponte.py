"""Ponte Raio-X → IN-360: espelha as despesas do Raio-X antigo até o módulo ser portado.

Recebe na entrada padrão o JSON exportado (somente leitura) do banco do Raio-X
por `automations/tools/ponte_raiox.py` e roda dentro do contêiner da API:

    ... | python -m modules.raiox_dre.ponte --tenant rodiza [--simular]

Espelho por mês: para cada mês presente na exportação, insere o que é novo, atualiza
o que mudou e remove o que sumiu da origem (chave: loja + mês + id_original, a mesma
do Raio-X). Meses ausentes da exportação não são tocados.

Também liga cada nome de fornecedor do GCOM ao cadastro (CRM) pela razão social,
guardando o nome do GCOM em `fornecedores.apelidos`. Nome sem par vira relatório.
"""
import argparse
import json
import re
import sys
import unicodedata
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import null, select

import modules.models  # noqa: F401
from core.audit import registrar
from core.db import nova_sessao, usar_tenant
from modules.pagamentos.models import Fornecedor
from modules.raiox_dre.models import Despesa
from modules.tenants.models import Loja, Tenant

CAMPOS = ("doc", "valor", "venc", "entrada", "fornecedor", "desembolso", "sub", "status_gcom",
          "observacoes_gcom", "observacoes_lida_em", "data_pagamento", "sub_itens")
_DATAS = {"venc", "entrada", "data_pagamento"}


def normalizar(texto: str | None) -> str:
    """'JM Comércio e Distribuição Ltda - EPP (JM Alimentos)' → 'JM COMERCIO E DISTRIBUICAO LTDA EPP JM ALIMENTOS'."""
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", sem_acento.upper()).split())


def _valor_campo(campo: str, v):
    if v is None:
        return None
    if campo in _DATAS:
        return date.fromisoformat(v[:10])
    if campo == "observacoes_lida_em":
        return datetime.fromisoformat(v)
    if campo == "valor":
        return Decimal(str(v)).quantize(Decimal("0.01"))
    return v


def ligar_fornecedores(fornecedores: list[Fornecedor], nomes_gcom: set[str]) -> tuple[list[str], list[str], list[str]]:
    """Acrescenta o nome do GCOM aos apelidos do fornecedor cuja razão social está contida nele.
    Devolve (ligados_agora, ja_ligados, sem_par)."""
    por_apelido = {normalizar(a): f for f in fornecedores for a in f.apelidos}
    ligados, ja, sem_par = [], [], []
    for nome in sorted(nomes_gcom):
        n = normalizar(nome)
        if n in por_apelido:
            ja.append(nome)
            continue
        candidatos = [f for f in fornecedores if f.razao_social and normalizar(f.razao_social)
                      and f" {normalizar(f.razao_social)} " in f" {n} "]
        if len(candidatos) == 1:
            f = candidatos[0]
            f.apelidos = [*f.apelidos, nome]
            por_apelido[n] = f
            ligados.append(f"{nome}  →  {f.nome}")
        else:
            sem_par.append(nome + (f"  (ambíguo: {', '.join(c.nome for c in candidatos)})" if candidatos else ""))
    return ligados, ja, sem_par


def espelhar(tenant_codigo: str, linhas: list[dict], simular: bool) -> list[str]:
    relato: list[str] = []
    with nova_sessao() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.codigo == tenant_codigo))
        if tenant is None:
            sys.exit(f"Cliente '{tenant_codigo}' não existe.")
        lojas = {l.nome: l for l in db.scalars(select(Loja).where(Loja.tenant_id == tenant.id))}
        faltando = sorted({l["loja_nome"] for l in linhas} - set(lojas))
        if faltando:
            sys.exit(f"Loja(s) do Raio-X sem par no IN-360 (cadastre com o mesmo nome): {', '.join(faltando)}")

        novos = alterados = removidos = iguais = 0
        grupos: dict[tuple[int, str], list[dict]] = {}
        for l in linhas:
            grupos.setdefault((lojas[l["loja_nome"]].id, l["mes"]), []).append(l)
        for (loja_id, mes), origem in sorted(grupos.items()):
            atuais = {d.id_original: d for d in db.scalars(select(Despesa).where(Despesa.loja_id == loja_id,
                                                                                Despesa.mes == mes))}
            vistos = set()
            for l in origem:
                vistos.add(l["id_original"])
                valores = {c: _valor_campo(c, l.get(c)) for c in CAMPOS}
                d = atuais.get(l["id_original"])
                # sub_itens vazio = NULL de SQL (como no Raio-X), não o valor JSON null
                gravar = {**valores, "sub_itens": valores["sub_itens"] if valores["sub_itens"] is not None else null()}
                if d is None:
                    db.add(Despesa(loja_id=loja_id, mes=mes, id_original=l["id_original"], **gravar))
                    novos += 1
                elif any(getattr(d, c) != v for c, v in valores.items()):
                    for c, v in gravar.items():
                        setattr(d, c, v)
                    alterados += 1
                else:
                    iguais += 1
            for id_original, d in atuais.items():
                if id_original not in vistos:
                    db.delete(d)
                    removidos += 1
        meses = sorted({m for _, m in grupos})
        relato.append(f"Despesas: {len(linhas)} lidas do Raio-X · {novos} novas · {alterados} alteradas · "
                      f"{removidos} removidas (sumiram da origem) · {iguais} iguais")
        relato.append(f"Meses espelhados: {', '.join(meses) if meses else '(nenhum)'}")

        usar_tenant(db, tenant.id)
        fornecedores = db.scalars(select(Fornecedor).where(Fornecedor.tenant_id == tenant.id)).all()
        ligados, ja, sem_par = ligar_fornecedores(list(fornecedores), {l["fornecedor"] for l in linhas})
        relato.append(f"\nFornecedores do GCOM ligados ao CRM agora: {len(ligados)} · já ligados: {len(ja)} · "
                      f"sem par no CRM: {len(sem_par)}")
        relato += [f"  [ligado ] {x}" for x in ligados]
        relato += [f"  [sem par] {x}" for x in sem_par]

        registrar(db, "ponte_raiox_espelho", "tenant", tenant.id, tenant_id=tenant.id,
                  detalhes={"lidas": len(linhas), "novas": novos, "alteradas": alterados, "removidas": removidos,
                            "meses": meses, "ligados": len(ligados), "simulacao": simular})
        if simular:
            db.rollback()
            relato.append("\nSIMULAÇÃO: nada foi gravado.")
        else:
            db.commit()
    return relato


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m modules.raiox_dre.ponte")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()
    linhas = json.load(sys.stdin)
    if not isinstance(linhas, list):
        sys.exit("Entrada inválida: esperado um array JSON de despesas.")
    print("\n".join(espelhar(a.tenant, linhas, a.simular)))


if __name__ == "__main__":
    main()
