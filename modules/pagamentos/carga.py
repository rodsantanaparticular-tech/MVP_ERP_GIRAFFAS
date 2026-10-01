"""Carga inicial do CRM de fornecedores a partir do seed JSON (roda dentro do contêiner da API):

    python -m modules.pagamentos.carga --tenant rodiza --arquivo database/seeds/fornecedores_rodiza.json
    python -m modules.pagamentos.carga ... --simular      # mostra o que faria, sem gravar

Idempotente: fornecedor (por nome), padrão vigente e despesa recorrente (por descrição)
que já existem NÃO são alterados. Nada é inventado: o que o seed não traz fica em branco.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

import modules.models  # noqa: F401
from core.audit import registrar
from core.db import nova_sessao, usar_tenant
from modules.pagamentos.models import TIPOS_PADRAO, DespesaRecorrente, Fornecedor, PadraoPagamento
from modules.pagamentos.router import normalizar_cnpj
from modules.tenants.models import Tenant

# Os padrões valem desde o início do período auditado que gerou o CRM (Jan–Set/2026).
VIGENCIA_PADRAO = date(2026, 1, 1)


def nome_e_apelidos(apelido: str) -> tuple[str, list[str]]:
    """'RFG ("MB" no extrato)' → ('RFG', ['MB']). Parênteses sem aspas ficam no nome: 'Claro (TV)'."""
    m = re.match(r'^(.*?)\s*\((.*)\)\s*$', apelido)
    if m and '"' in m.group(2):
        return m.group(1).strip(), re.findall(r'"([^"]+)"', m.group(2))
    return apelido.strip(), []


def faixa_dias(texto: str) -> tuple[int, int]:
    """'05' → (5, 5) · '05-08' → (5, 8)."""
    partes = [int(p) for p in re.findall(r"\d{1,2}", texto)]
    if not partes or len(partes) > 2:
        raise ValueError(f"dia_mes inesperado: {texto!r}")
    return partes[0], partes[-1]


def _valor_br(s: str) -> Decimal:
    return Decimal(s.replace(".", "").replace(",", "."))


def faixa_valor(texto: str) -> tuple[Decimal | None, Decimal | None, bool]:
    """'R$ 38.000 – 44.000' → (38000, 44000, False) · 'R$ 552,94' → (552.94, 552.94, False)
    · 'variável (% faturamento)' → (None, None, True)."""
    numeros = re.findall(r"\d[\d.]*(?:,\d{1,2})?", texto)
    if not numeros:
        return None, None, "vari" in texto.lower()
    valores = [_valor_br(n) for n in numeros[:2]]
    return valores[0], valores[-1], False


def encerramento(observacao: str | None) -> date | None:
    """'Parcela 8/8 venceu 20/06/2026 — não deve se repetir' → 2026-06-20."""
    if not observacao or "não deve se repetir" not in observacao:
        return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", observacao)
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def fornecedor_da_descricao(descricao: str, por_nome: dict[str, int]) -> int | None:
    """Liga 'Multiplan (CAM + aluguel...)' a 'Multiplan / BH Shopping' pela 1ª palavra do nome."""
    primeira = descricao.split()[0].lower()
    achados = [fid for nome, fid in por_nome.items() if re.split(r"[\s/(]+", nome)[0].lower() == primeira]
    return achados[0] if len(achados) == 1 else None


def carregar(tenant_codigo: str, arquivo: Path, simular: bool) -> list[str]:
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    relato: list[str] = []
    with nova_sessao() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.codigo == tenant_codigo))
        if tenant is None:
            sys.exit(f"Cliente '{tenant_codigo}' não existe.")
        usar_tenant(db, tenant.id)

        existentes = {f.nome: f for f in db.scalars(select(Fornecedor).where(Fornecedor.tenant_id == tenant.id))}
        for item in dados["fornecedores"]:
            nome, apelidos = nome_e_apelidos(item["apelido"])
            f = existentes.get(nome)
            if f is None:
                f = Fornecedor(tenant_id=tenant.id, nome=nome, apelidos=apelidos, ativo=True,
                               razao_social=item.get("razao_social"), cnpj=normalizar_cnpj(item.get("cnpj")),
                               categoria=item.get("categoria"), prazo_pagamento=item.get("prazo_pagamento"),
                               endereco=item.get("endereco"), observacoes=item.get("observacoes"))
                db.add(f)
                db.flush()
                existentes[nome] = f
                relato.append(f"[criado ] fornecedor {nome}" + (f" (apelidos: {', '.join(apelidos)})" if apelidos
                                                                  else ""))
            else:
                relato.append(f"[existe ] fornecedor {nome}")

            tipo = item.get("padrao")
            if tipo not in TIPOS_PADRAO:
                relato.append(f"[aviso  ]   padrão desconhecido {tipo!r}: não cadastrado")
                continue
            vigente = db.scalar(select(PadraoPagamento).where(PadraoPagamento.fornecedor_id == f.id,
                                                             PadraoPagamento.vigencia_fim.is_(None)))
            if vigente is None:
                db.add(PadraoPagamento(tenant_id=tenant.id, fornecedor_id=f.id, tipo=tipo,
                                       vigencia_inicio=VIGENCIA_PADRAO, observacao="carga inicial do CRM"))
                relato.append(f"[criado ]   padrão {tipo} desde {VIGENCIA_PADRAO:%d-%m-%Y}")
            else:
                relato.append(f"[existe ]   padrão {vigente.tipo}")
        db.flush()

        por_nome = {nome: f.id for nome, f in existentes.items()}
        ja = {r.descricao for r in db.scalars(select(DespesaRecorrente)
                                              .where(DespesaRecorrente.tenant_id == tenant.id))}
        for item in dados["despesas_fixas"]:
            descricao = item["fornecedor"]
            if descricao in ja:
                relato.append(f"[existe ] recorrente {descricao}")
                continue
            dia_ini, dia_fim = faixa_dias(item["dia_mes"])
            vmin, vmax, variavel = faixa_valor(item["valor_aproximado"])
            fim = encerramento(item.get("observacao"))
            forn = fornecedor_da_descricao(descricao, por_nome)
            db.add(DespesaRecorrente(tenant_id=tenant.id, fornecedor_id=forn, descricao=descricao,
                                     dia_inicio=dia_ini, dia_fim=dia_fim, valor_min=vmin, valor_max=vmax,
                                     valor_variavel=variavel, vigencia_fim=fim, ativo=fim is None,
                                     observacao=item.get("observacao")))
            faixa = "variável" if variavel else (f"R$ {vmin}" if vmin == vmax else f"R$ {vmin}–{vmax}")
            relato.append(f"[criado ] recorrente dia {dia_ini:02d}-{dia_fim:02d} {faixa} · {descricao}"
                          + ("" if forn else " · sem fornecedor ligado")
                          + (f" · ENCERRADA em {fim:%d-%m-%Y}" if fim else ""))

        registrar(db, "crm_fornecedores_carregado", "tenant", tenant.id, tenant_id=tenant.id,
                  detalhes={"arquivo": arquivo.name, "linhas": len(relato),
                            "em": datetime.now().isoformat(timespec="seconds")})
        if simular:
            db.rollback()
            relato.append("\nSIMULAÇÃO: nada foi gravado.")
        else:
            db.commit()
    return relato


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m modules.pagamentos.carga")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--arquivo", required=True, type=Path)
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()
    print("\n".join(carregar(a.tenant, a.arquivo, a.simular)))


if __name__ == "__main__":
    main()
