"""Passo 5c-3: conciliação banco × GCOM gravada no banco + API e permissões."""
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import modules.models  # noqa: F401
from api.main import app
from core.db import nova_sessao, usar_tenant
from modules.banco.models import ExtratoLancamento
from modules.banco.servico import importar_arquivo
from modules.conciliacao.models import Conciliacao
from modules.pagamentos.carga import carregar
from modules.pagamentos.models import Fornecedor
from modules.raiox_dre.ponte import espelhar as espelhar_despesas
from tests.test_banco import _bradesco
from tests.test_etapa1_seguranca_cofre import _sufixo, criar_usuario, login
from tests.test_painel_fornecedores import RFG, _d

client = TestClient(app)
SEED = Path(__file__).resolve().parents[1] / "database" / "seeds" / "fornecedores_rodiza.json"
D = Decimal


@pytest.fixture(scope="module")
def cen(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("conc")
    adm = login(criar_usuario("plataforma_admin"))
    codigo = f"k{_sufixo()}"
    tid = client.post("/tenants", headers=adm, json={"rede_codigo": "giraffas", "codigo": codigo,
                                                     "razao_social": "Cliente Conciliação"}).json()["id"]
    loja = client.post(f"/tenants/{tid}/lojas", headers=adm,
                       json={"nome": "Shopping BH", "filial_sigla": "GSHBH"}).json()["id"]
    carregar(codigo, SEED, simular=False)
    espelhar_despesas(codigo, [
        _d(1, "2026-08", 1500.0),                              # RFG, venc 20/08: pago 21/08 → batido
        _d(2, "2026-08", 777.0),                               # RFG: sem pagamento no banco
        _d(3, "2026-08", 450.0, fornecedor="FORNECEDOR SEM CRM LTDA", desembolso="MANUTENÇÃO", sub="REPAROS"),
    ], simular=False)
    arq = _bradesco(tmp / "Bradesco_ago_conc.xlsx", D("10000"), [
        ("21/08/2026", "PAGTO ELETRON  COBRANCA RFG COMERCIO", D("-1500")),
        ("20/08/2026", "PAGTO ELETRON  COBRANCA QUALQUER", D("-450")),       # sem fornecedor: sugerido
        ("22/08/2026", "TARIFA BANCARIA", D("-12.34"))])                       # sem documento
    with nova_sessao() as db:
        usar_tenant(db, tid)
        assert importar_arquivo(db, tid, arq).startswith("[importado]")
        rfg = db.scalar(select(Fornecedor).where(Fornecedor.tenant_id == tid, Fornecedor.nome == "RFG"))
        l = db.scalar(select(ExtratoLancamento).where(ExtratoLancamento.tenant_id == tid,
                                                      ExtratoLancamento.valor == D("-1500")))
        l.fornecedor_id = rfg.id
        db.commit()
    return {"adm": adm, "tenant": tid, "loja": loja}


def test_rodar_resumo_e_lista(cen):
    tid, adm = cen["tenant"], cen["adm"]
    r = client.post(f"/tenants/{tid}/conciliacao/rodar", headers=adm)
    assert r.status_code == 200, r.text
    assert (r.json()["batido"], r.json()["sugerido"]) == (1, 1)

    lista = client.get(f"/tenants/{tid}/conciliacao?mes=2026-08", headers=adm).json()
    st = {c["status"]: c for c in lista}
    assert st["batido"]["regra"] == "um_para_um" and float(st["batido"]["diferenca"]) == 0
    assert st["batido"]["documentos"][0]["fornecedor"] == RFG
    assert st["sugerido"]["documentos"][0]["fornecedor"] == "FORNECEDOR SEM CRM LTDA"

    ago = next(m for m in client.get(f"/tenants/{tid}/conciliacao/resumo", headers=adm).json() if m["mes"] == "2026-08")
    assert ago["sem_documento"]["qtd"] == 1 and D(str(ago["sem_documento"]["valor"])) == D("12.34")
    assert ago["sem_pagamento"]["qtd"] == 1 and D(str(ago["sem_pagamento"]["valor"])) == D("777.00")

    # idempotente: rodar de novo não duplica
    client.post(f"/tenants/{tid}/conciliacao/rodar", headers=adm)
    assert len(client.get(f"/tenants/{tid}/conciliacao", headers=adm).json()) == 2


def test_confirmado_por_humano_nao_e_refeito(cen):
    tid, adm = cen["tenant"], cen["adm"]
    with nova_sessao() as db:
        usar_tenant(db, tid)
        c = db.scalar(select(Conciliacao).where(Conciliacao.tenant_id == tid, Conciliacao.status == "sugerido"))
        c.status, c.confirmado_por = "batido", 1
        db.commit()
        cid = c.id
    r = client.post(f"/tenants/{tid}/conciliacao/rodar", headers=adm).json()
    assert r.get("sugerido", 0) == 0 and r["batido"] == 1
    ids = {c["id"] for c in client.get(f"/tenants/{tid}/conciliacao", headers=adm).json()}
    assert cid in ids and len(ids) == 2


def test_permissoes(cen):
    tid = cen["tenant"]
    gestor = login(criar_usuario("gestor_loja", tid, cen["loja"]))      # conciliacao:ler, mas sem banco:ler
    assert client.get(f"/tenants/{tid}/conciliacao/resumo", headers=gestor).status_code == 403
    franq = login(criar_usuario("franqueado_admin", tid))                 # lê, não opera
    assert client.get(f"/tenants/{tid}/conciliacao/resumo", headers=franq).status_code == 200
    assert client.post(f"/tenants/{tid}/conciliacao/rodar", headers=franq).status_code == 403
    assert client.get(f"/tenants/{tid}/conciliacao?mes=2026-13", headers=franq).status_code == 422
