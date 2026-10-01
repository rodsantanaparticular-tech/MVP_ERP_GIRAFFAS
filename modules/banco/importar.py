"""Importa extratos (roda dentro da API; os arquivos ficam em C:\\giraffas-erp-data\\entrada\\extratos):

    python -m modules.banco.importar --tenant rodiza /data/entrada/extratos [--simular]

Aceita pastas e arquivos. Idempotente: arquivo já importado (mesmo hash) é pulado e lançamento
repetido entre arquivos sobrepostos não duplica (conta + data + histórico + valor + ocorrência).
Arquivo cujo saldo corrido não fecha é RECUSADO (use --aceitar-quebras só com motivo).
No fim, classifica o que entrou (regras de texto + transferências entre contas; ver classificacao.py).
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import select

import modules.models  # noqa: F401
from core.audit import registrar
from core.db import nova_sessao, usar_tenant
from modules.banco.classificacao import classificar
from modules.banco.models import ContaBancaria
from modules.banco.servico import importar_arquivo, lacunas
from modules.tenants.models import Tenant

EXTENSOES = {".xlsx", ".xls", ".csv"}


def arquivos(caminhos: list[Path]) -> list[Path]:
    saida = []
    for c in caminhos:
        saida += sorted(p for p in c.iterdir() if p.suffix.lower() in EXTENSOES) if c.is_dir() else [c]
    return saida


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m modules.banco.importar")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("caminhos", nargs="+", type=Path)
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-quebras", action="store_true")
    a = ap.parse_args()
    with nova_sessao() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.codigo == a.tenant))
        if tenant is None:
            sys.exit(f"Cliente '{a.tenant}' não existe.")
        usar_tenant(db, tenant.id)
        relato = [importar_arquivo(db, tenant.id, p, aceitar_quebras=a.aceitar_quebras) for p in arquivos(a.caminhos)]
        db.flush()
        relato.append(f"\nClassificação: {classificar(db, tenant.id)}")
        relato.append("\nBuracos no extrato (onde o saldo não fecha com o lançamento anterior):")
        for c in db.scalars(select(ContaBancaria).where(ContaBancaria.tenant_id == tenant.id)):
            bs = lacunas(db, c.id)
            relato.append(f"  {c.apelido}: {'nenhum' if not bs else len(bs)}")
            relato += [f"    entre {b.depois_de:%d-%m-%Y} e {b.antes_de:%d-%m-%Y}: faltam R$ {b.faltando:,.2f} "
                       "de movimento líquido" for b in bs]
        registrar(db, "extratos_importados", "tenant", tenant.id, tenant_id=tenant.id,
                  detalhes={"arquivos": len(relato), "simulacao": a.simular})
        if a.simular:
            db.rollback()
            relato.append("\nSIMULAÇÃO: nada foi gravado.")
        else:
            db.commit()
    print("\n".join(relato))


if __name__ == "__main__":
    main()
