"""Classifica o extrato: favorecido e classificação de cada lançamento (roda dentro da API):

    python -m modules.banco.classificar --tenant rodiza \\
        --planilha /data/entrada/extratos/15_Bradesco_tratado_2026_08_Atualizado.xlsx --banco Bradesco \\
        --dicionario database/seeds/extrato_favorecidos_rodiza.json \
        --categorias database/seeds/categorias_caixa_rodiza.json [--simular]
    python -m modules.banco.classificar --tenant rodiza          # só regras + transferências

Com --planilha: copia o que o usuário já classificou (linha a linha) e aprende uma regra por chave de
texto. Com --dicionario: grava as regras manuais dele. Com --categorias: carrega a tabela classe →
categoria do DRE (visão caixa). Depois, sempre: aplica as regras ao resto e marca as transferências entre contas próprias.
Idempotente. Classificação `manual` nunca é tocada. Ver modules/banco/classificacao.py.
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import select

import modules.models  # noqa: F401
from core.audit import registrar
from core.db import nova_sessao, usar_tenant
from modules.banco.classificacao import (Dicionario, classificar, cobertura, gravar_categorias, gravar_regras_manuais,
                                         ler_planilha, semear_da_planilha)
from modules.banco.models import ContaBancaria
from modules.tenants.models import Tenant


def _brl(v) -> str:
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m modules.banco.classificar")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--planilha", type=Path)
    ap.add_argument("--banco", help="conta da planilha (apelido, ex.: Bradesco)")
    ap.add_argument("--dicionario", type=Path)
    ap.add_argument("--categorias", type=Path)
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()
    if a.planilha and not a.banco:
        sys.exit("--planilha exige --banco (a planilha não diz de qual conta é).")
    relato = []
    with nova_sessao() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.codigo == a.tenant))
        if tenant is None:
            sys.exit(f"Cliente '{a.tenant}' não existe.")
        usar_tenant(db, tenant.id)
        detalhes = {"simulacao": a.simular}
        dic = Dicionario.ler(a.dicionario)
        if a.categorias:
            n = gravar_categorias(db, tenant.id, a.categorias)
            relato.append(f"Categorias do DRE (visão caixa): {n} itens em {a.categorias.name}")
            detalhes["categorias"] = n
        if dic.regras_manuais:
            n = gravar_regras_manuais(db, tenant.id, dic)
            relato.append(f"Regras manuais: {n} (de {a.dicionario.name})")
            detalhes["regras_manuais"] = n
        if a.planilha:
            conta = db.scalar(select(ContaBancaria).where(ContaBancaria.tenant_id == tenant.id,
                                                          ContaBancaria.apelido == a.banco))
            if conta is None:
                sys.exit(f"Conta '{a.banco}' não existe para {a.tenant}.")
            r = semear_da_planilha(db, tenant.id, conta, ler_planilha(a.planilha, dic), dic)
            relato += [f"Planilha {a.planilha.name}: {r.linhas_planilha} linhas · {r.pareadas} ligadas ao extrato · "
                       f"{len(r.sem_par)} sem par",
                       *[f"  sem par: {p.data:%d-%m-%Y} {_brl(p.valor)} {p.historico}" for p in r.sem_par[:20]],
                       f"Regras: {r.regras_novas} novas · {r.regras_atualizadas} atualizadas · {r.regras_desligadas} desligadas · "
                       f"{len(r.regras_sem_classificacao)} só com favorecido (o texto não decide a classificação):",
                       *[f"  {x}" for x in r.regras_sem_classificacao]]
            relato.append(f"Linhas da planilha com texto diferente do banco (não ensinam regra; revisar): "
                          f"{len(r.texto_diferente)}")
            relato += [f"  {p.data:%d-%m-%Y} {_brl(p.valor)} planilha: '{p.historico}' → banco: '{h}' · "
                       f"{p.classificacao}/{p.favorecido}" for p, h in r.texto_diferente[:30]]
            if r.fornecedores_faltando:
                relato.append(f"⚠️ Fornecedores do dicionário que não existem no CRM: {', '.join(r.fornecedores_faltando)}")
            detalhes.update(planilha=a.planilha.name, pareadas=r.pareadas, sem_par=len(r.sem_par),
                            regras_novas=r.regras_novas, regras_atualizadas=r.regras_atualizadas)
        resumo = classificar(db, tenant.id)
        relato.append(str(resumo))
        relato += [f"  calendário: {l.data:%d-%m-%Y} {_brl(l.valor)} {l.favorecido}: {antes} → {l.classificacao}"
                   for l, antes in resumo.trocas_calendario]
        relato.append("\nCobertura (lançamentos com favorecido):")
        for g in cobertura(db, tenant.id):
            feitos = g["total"] - g["por_origem"].get("pendente", 0)
            origens = ", ".join(f"{k} {v}" for k, v in sorted(g["por_origem"].items()))
            relato.append(f"  {g['conta']} {'entradas' if g['natureza'] == 'C' else 'saídas'}: {feitos}/{g['total']} "
                          f"({origens}) · pendente {_brl(g['valor_pendente'])} de {_brl(g['valor_total'])}")
            relato += [f"      {q:>4}× {_brl(v):>16}  {k}" for k, q, v in g["pendentes"][:12]]
        detalhes["resumo"] = str(resumo)
        detalhes["trocas_calendario"] = [{"data": l.data.isoformat(), "valor": str(l.valor), "antes": antes,
                                          "depois": l.classificacao} for l, antes in resumo.trocas_calendario]
        registrar(db, "extrato_classificado", "tenant", tenant.id, tenant_id=tenant.id, detalhes=detalhes)
        if a.simular:
            db.rollback()
            relato.append("\nSIMULAÇÃO: nada foi gravado.")
        else:
            db.commit()
    print("\n".join(relato))


if __name__ == "__main__":
    main()
