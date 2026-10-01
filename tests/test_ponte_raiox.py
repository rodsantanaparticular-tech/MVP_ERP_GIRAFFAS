"""Ponte Raio-X → IN-360: espelho por mês + ligação dos nomes do GCOM ao CRM."""
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import modules.models  # noqa: F401
from api.main import app
from core.db import nova_sessao, usar_tenant
from modules.pagamentos.carga import carregar
from modules.pagamentos.models import Fornecedor
from modules.raiox_dre.models import Despesa
from modules.raiox_dre.ponte import espelhar, normalizar
from tests.test_etapa1_seguranca_cofre import _sufixo, criar_usuario, login

client = TestClient(app)
SEED = Path(__file__).resolve().parents[1] / "database" / "seeds" / "fornecedores_rodiza.json"


def _linha(id_original, mes="2026-08", valor=100.0, fornecedor="RFG COMERCIO TRANSPORTES E SERVIÇOS LTDA GUARULHOS",
           **extra):
    base = {"loja_nome": "Shopping BH", "mes": mes, "id_original": id_original, "doc": f"D{id_original}",
            "valor": valor, "venc": f"{mes}-20", "entrada": f"{mes}-01", "fornecedor": fornecedor,
            "desembolso": "INSUMOS", "sub": "PROTEINAS", "status_gcom": "PAGO", "observacoes_gcom": None,
            "observacoes_lida_em": None, "data_pagamento": None, "sub_itens": None}
    return {**base, **extra}


@pytest.fixture(scope="module")
def cliente():
    adm = login(criar_usuario("plataforma_admin"))
    codigo = f"r{_sufixo()}"
    tid = client.post("/tenants", headers=adm, json={"rede_codigo": "giraffas", "codigo": codigo,
                                                     "razao_social": "Cliente Ponte"}).json()["id"]
    loja = client.post(f"/tenants/{tid}/lojas", headers=adm, json={"nome": "Shopping BH", "filial_sigla": "GSHBH"})
    carregar(codigo, SEED, simular=False)
    return {"codigo": codigo, "tenant": tid, "loja": loja.json()["id"]}


def _despesas(loja_id):
    with nova_sessao() as db:
        return {(d.mes, d.id_original): d for d in db.scalars(select(Despesa).where(Despesa.loja_id == loja_id))}


def test_normalizar():
    assert normalizar("JM Comércio e Distribuição Ltda - EPP (JM Alimentos)") == \
        "JM COMERCIO E DISTRIBUICAO LTDA EPP JM ALIMENTOS"


def test_espelho_insere_atualiza_remove_e_e_idempotente(cliente):
    cod, loja = cliente["codigo"], cliente["loja"]
    espelhar(cod, [_linha(1), _linha(2), _linha(3, mes="2026-07")], simular=False)
    assert set(_despesas(loja)) == {("2026-08", 1), ("2026-08", 2), ("2026-07", 3)}

    # agosto: 1 muda de valor, 2 some da origem, 4 é novo. Julho não vem na exportação: fica intocado.
    relato = espelhar(cod, [_linha(1, valor=150.0), _linha(4)], simular=False)
    assert "1 novas · 1 alteradas · 1 removidas" in relato[0]
    d = _despesas(loja)
    assert set(d) == {("2026-08", 1), ("2026-08", 4), ("2026-07", 3)}
    assert d[("2026-08", 1)].valor == Decimal("150.00")

    relato = espelhar(cod, [_linha(1, valor=150.0), _linha(4)], simular=False)
    assert "0 novas · 0 alteradas · 0 removidas" in relato[0] and "· 2 iguais" in relato[0]

    relato = espelhar(cod, [_linha(9)], simular=True)
    assert relato[-1].strip().startswith("SIMULAÇÃO") and ("2026-08", 9) not in _despesas(loja)


def test_liga_nomes_do_gcom_ao_crm(cliente):
    cod, tid = cliente["codigo"], cliente["tenant"]
    relato = espelhar(cod, [
        _linha(10, fornecedor="RFG COMERCIO TRANSPORTES E SERVIÇOS LTDA GUARULHOS"),
        _linha(11, fornecedor="JM COMERCIO E DISTRIBUICAO LTDA - EPP JM ALIMENTOS"),
        _linha(12, fornecedor="KELMINAS AGROINDUSTRIA E COM DE ALIM. LTDA KELMINAS"),
        _linha(13, fornecedor="SPAL INDUSTRIA BRASILEIRA DE BEBIDAS S/A SPAL"),
        _linha(14, fornecedor="MULTIPLAN ADMINISTRADORA DE ESTACIONAMENTO LTDA MULTIPLAN ADMINISTRA"),
    ], simular=False)
    texto = "\n".join(relato)
    assert "[sem par] SPAL INDUSTRIA" in texto
    assert "[sem par] MULTIPLAN ADMINISTRADORA DE ESTACIONAMENTO" in texto   # não é a Multiplan Arrecadadora
    with nova_sessao() as db:
        usar_tenant(db, tid)
        f = {x.nome: x for x in db.scalars(select(Fornecedor).where(Fornecedor.tenant_id == tid))}
    assert f["RFG"].apelidos == ["MB", "RFG COMERCIO TRANSPORTES E SERVIÇOS LTDA GUARULHOS"]
    assert "JM COMERCIO E DISTRIBUICAO LTDA - EPP JM ALIMENTOS" in f["JM"].apelidos
    assert "KELMINAS AGROINDUSTRIA E COM DE ALIM. LTDA KELMINAS" in f["Kelminas"].apelidos
    # segunda rodada: não duplica apelido
    espelhar(cod, [_linha(10)], simular=False)
    with nova_sessao() as db:
        usar_tenant(db, tid)
        rfg = db.scalar(select(Fornecedor).where(Fornecedor.tenant_id == tid, Fornecedor.nome == "RFG"))
    assert rfg.apelidos.count("RFG COMERCIO TRANSPORTES E SERVIÇOS LTDA GUARULHOS") == 1


def test_loja_sem_par_para_tudo(cliente):
    with pytest.raises(SystemExit, match="sem par no IN-360"):
        espelhar(cliente["codigo"], [_linha(20, loja_nome="Loja Fantasma")], simular=False)


def test_sub_itens_vazio_vira_null_de_sql(cliente):
    from sqlalchemy import text
    espelhar(cliente["codigo"], [_linha(30, mes="2026-05"),
                                 _linha(31, mes="2026-05", sub_itens=[{"tipo": "OCUPAÇÃO", "sub": "IPTU", "valor": 100.0}])],
             simular=False)
    with nova_sessao() as db:
        linhas = dict(db.execute(text("SELECT id_original, sub_itens IS NULL FROM despesas "
                                      "WHERE loja_id = :l AND mes = '2026-05'"), {"l": cliente["loja"]}).all())
    assert linhas == {30: True, 31: False}
