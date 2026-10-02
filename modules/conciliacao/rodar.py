"""Roda o motor de conciliação banco × GCOM (dentro da API):

    python -m modules.conciliacao.rodar --tenant rodiza [--simular]

Refaz só o que o motor criou e ninguém confirmou. Ver modules/conciliacao/motor.py e servico.py.
"""
import argparse
import sys

from sqlalchemy import select

import modules.models  # noqa: F401
from core.audit import registrar
from core.db import nova_sessao, usar_tenant
from modules.conciliacao.servico import resumo, rodar
from modules.tenants.models import Tenant


def _brl(v) -> str:
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m modules.conciliacao.rodar")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()
    with nova_sessao() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.codigo == a.tenant))
        if tenant is None:
            sys.exit(f"Cliente '{a.tenant}' não existe.")
        usar_tenant(db, tenant.id)
        cont = rodar(db, tenant.id)
        print(f"Débitos avaliados: {cont['debitos_avaliados']} · documentos: {cont['documentos_avaliados']}")
        for st in ("batido", "sugerido", "investigar"):
            print(f"  {st}: {cont.get(st, 0)}")
        print("\nMês      batido  sugerido  investigar   sem documento (banco)      sem pagamento (GCOM)")
        for m in resumo(db, tenant.id):
            s = m["status"]
            print(f"{m['mes']}  {s.get('batido', {}).get('qtd', 0):>6}  {s.get('sugerido', {}).get('qtd', 0):>8}"
                  f"  {s.get('investigar', {}).get('qtd', 0):>10}   {m['sem_documento']['qtd']:>4} {_brl(m['sem_documento']['valor']):>18}"
                  f"   {m['sem_pagamento']['qtd']:>4} {_brl(m['sem_pagamento']['valor']):>18}")
        if a.simular:
            db.rollback()
            print("\nSIMULAÇÃO: nada gravado.")
            return
        registrar(db, "conciliacao.motor", "conciliacoes", tenant_id=tenant.id, detalhes=cont)
        db.commit()


if __name__ == "__main__":
    main()
