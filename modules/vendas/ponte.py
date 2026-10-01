"""Ponte Gestão → IN-360: espelha o faturamento diário (database_realizado_dia.csv).

Recebe na entrada padrão o JSON montado por `automations/tools/ponte_gestao.py` e roda na API:

    ... | python -m modules.vendas.ponte --tenant rodiza --loja-sigla GSHBH [--simular]

Espelho no intervalo de datas recebido: insere o novo, atualiza o que mudou e remove o dia que
sumiu da origem. Dias fora do intervalo não são tocados.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select

import modules.models  # noqa: F401
from core.audit import registrar
from core.db import nova_sessao, usar_tenant
from modules.tenants.models import Loja, Tenant
from modules.vendas.models import RealizadoDia

FONTE = "gestao_realizado_dia"
_NUM = {"faturamento": "0.01", "tm": "0.0001", "adc": "0.01", "beb": "0.01", "sob": "0.01"}


def _campos(l: dict) -> dict:
    out = {}
    for c, casas in _NUM.items():
        v = l.get(c)
        out[c] = None if v in (None, "") else Decimal(str(v)).quantize(Decimal(casas))
    out["tc"] = None if l.get("tc") in (None, "") else int(float(l["tc"]))
    out["origem"] = l.get("origem") or None
    return out


def espelhar(tenant_codigo: str, loja_sigla: str, linhas: list[dict], simular: bool) -> list[str]:
    with nova_sessao() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.codigo == tenant_codigo))
        if tenant is None:
            sys.exit(f"Cliente '{tenant_codigo}' não existe.")
        loja = db.scalar(select(Loja).where(Loja.tenant_id == tenant.id, Loja.filial_sigla == loja_sigla))
        if loja is None:
            sys.exit(f"Loja '{loja_sigla}' não existe no cliente '{tenant_codigo}'.")
        usar_tenant(db, tenant.id)
        if not linhas:
            return ["Nada recebido."]
        entrada = {date.fromisoformat(l["data"][:10]): _campos(l) for l in linhas}
        de, ate = min(entrada), max(entrada)
        atuais = {r.data: r for r in db.scalars(select(RealizadoDia).where(
            RealizadoDia.loja_id == loja.id, RealizadoDia.fonte == FONTE,
            RealizadoDia.data >= de, RealizadoDia.data <= ate))}
        novos = alterados = removidos = iguais = 0
        for dia, campos in entrada.items():
            r = atuais.get(dia)
            if r is None:
                db.add(RealizadoDia(tenant_id=tenant.id, loja_id=loja.id, data=dia, fonte=FONTE, **campos))
                novos += 1
            elif any(getattr(r, c) != v for c, v in campos.items()):
                for c, v in campos.items():
                    setattr(r, c, v)
                alterados += 1
            else:
                iguais += 1
        for dia, r in atuais.items():
            if dia not in entrada:
                db.delete(r)
                removidos += 1
        por_mes = defaultdict(Decimal)
        for dia, c in entrada.items():
            por_mes[f"{dia:%Y-%m}"] += c["faturamento"]
        relato = [f"Faturamento diário: {len(entrada)} dias ({de:%d-%m-%Y} a {ate:%d-%m-%Y}) · {novos} novos · "
                  f"{alterados} alterados · {removidos} removidos · {iguais} iguais"]
        relato += [f"  {m}: R$ {v:,.2f}" for m, v in sorted(por_mes.items())]
        registrar(db, "ponte_gestao_realizado", "loja", loja.id, tenant_id=tenant.id,
                  detalhes={"dias": len(entrada), "de": de.isoformat(), "ate": ate.isoformat(), "novos": novos,
                            "alterados": alterados, "removidos": removidos, "simulacao": simular})
        if simular:
            db.rollback()
            relato.append("SIMULAÇÃO: nada foi gravado.")
        else:
            db.commit()
    return relato


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m modules.vendas.ponte")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--loja-sigla", required=True)
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()
    linhas = json.load(sys.stdin)
    print("\n".join(espelhar(a.tenant, a.loja_sigla, linhas, a.simular)))


if __name__ == "__main__":
    main()
