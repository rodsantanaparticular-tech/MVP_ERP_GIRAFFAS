"""Painel de fornecedores (passo 4) + ponte do faturamento diário da Gestão."""
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import modules.models  # noqa: F401
from api.main import app
from core.db import nova_sessao, usar_tenant
from modules.pagamentos.carga import carregar
from modules.paineis.fornecedores import meses_disponiveis, montar
from modules.raiox_dre.ponte import espelhar as espelhar_despesas
from modules.vendas.ponte import espelhar as espelhar_vendas
from tests.test_etapa1_seguranca_cofre import _sufixo, criar_usuario, login

client = TestClient(app)
SEED = Path(__file__).resolve().parents[1] / "database" / "seeds" / "fornecedores_rodiza.json"
RFG = "RFG COMERCIO TRANSPORTES E SERVIÇOS LTDA GUARULHOS"


def _d(i, mes, valor, fornecedor=RFG, desembolso="INSUMOS", sub="PROTEINAS", sub_itens=None):
    return {"loja_nome": "Shopping BH", "mes": mes, "id_original": i, "doc": f"D{i}", "valor": valor,
            "venc": f"{mes}-20", "entrada": f"{mes}-01", "fornecedor": fornecedor, "desembolso": desembolso,
            "sub": sub, "status_gcom": "PAGO", "observacoes_gcom": None, "observacoes_lida_em": None,
            "data_pagamento": None, "sub_itens": sub_itens}


@pytest.fixture(scope="module")
def cen():
    adm = login(criar_usuario("plataforma_admin"))
    codigo = f"v{_sufixo()}"
    tid = client.post("/tenants", headers=adm, json={"rede_codigo": "giraffas", "codigo": codigo,
                                                     "razao_social": "Cliente Painel"}).json()["id"]
    loja = client.post(f"/tenants/{tid}/lojas", headers=adm,
                       json={"nome": "Shopping BH", "filial_sigla": "GSHBH"}).json()["id"]
    carregar(codigo, SEED, simular=False)
    espelhar_despesas(codigo, [
        _d(1, "2026-07", 600.0), _d(2, "2026-08", 800.0),
        _d(3, "2026-08", 200.0, fornecedor="SPAL INDUSTRIA BRASILEIRA DE BEBIDAS S/A SPAL", sub="BEBIDAS"),
        _d(4, "2026-08", 500.0, fornecedor="O PRÓPRIO ESCRITÓRIO", desembolso="PESSOAL", sub="SALARIOS"),
        _d(5, "2026-08", 1000.0, fornecedor="MULTIPLAN ARRECADADORA LTDA MULTIPLAN", desembolso="OCUPAÇÃO, UTILIDADES",
           sub="MÚLTIPLOS SUB-DESEMBOLSOS", sub_itens=[{"tipo": "OCUPAÇÃO", "sub": "ALUGUEL MINIMO", "valor": 700.0},
                                                       {"tipo": "UTILIDADES", "sub": "ENERGIA ELETRICA", "valor": 300.0}]),
        _d(6, "2026-01", 999.0),   # antes de fev/26: fora dos meses disponíveis
    ], simular=False)
    espelhar_vendas(codigo, "GSHBH", [{"data": "2026-08-01", "faturamento": "3000.00", "tc": "100"},
                                      {"data": "2026-08-02", "faturamento": "2000.00", "tc": "80"},
                                      {"data": "2026-07-15", "faturamento": "4000.00"}], simular=False)
    return {"adm": adm, "codigo": codigo, "tenant": tid, "loja": loja}


def _linha(dados, fornecedor, categoria=None):
    return next(l for l in dados["linhas"] if l["fornecedor"] == fornecedor
                and (categoria is None or l["categoria"] == categoria))


def test_montar_agrega_por_categoria_crm_e_escritorio(cen):
    with nova_sessao() as db:
        usar_tenant(db, cen["tenant"])
        assert meses_disponiveis(db, [cen["loja"]]) == ["2026-07", "2026-08"]
        d = montar(db, cen["tenant"], [cen["loja"]], ["2026-07", "2026-08"])
    assert d["receita"] == {"2026-07": Decimal("4000.00"), "2026-08": Decimal("5000.00")}
    assert d["total_despesas"] == {"2026-07": Decimal("600.00"), "2026-08": Decimal("2500.00")}
    rfg = _linha(d, "RFG")                                   # nome do GCOM resolvido para o CRM
    assert rfg["crm_id"] and rfg["padrao"] == "um_para_um" and rfg["valores"]["2026-08"] == Decimal("800.00")
    assert rfg["total"] == Decimal("1400.00") and rfg["documentos"] == 2
    assert _linha(d, "SPAL INDUSTRIA BRASILEIRA DE BEBIDAS S/A SPAL")["crm_id"] is None
    esc = _linha(d, "O Próprio Escritório — Salarios")
    assert esc["escritorio"] is True and esc["categoria"] == "PESSOAL"
    # documento rateado: cada categoria recebe a sua linha
    assert _linha(d, "Multiplan / BH Shopping", "OCUPAÇÃO")["valores"]["2026-08"] == Decimal("700.00")
    assert _linha(d, "Multiplan / BH Shopping", "UTILIDADES")["valores"]["2026-08"] == Decimal("300.00")
    cats = {c["categoria"]: c["total"] for c in d["categorias"]}
    assert cats["INSUMOS"] == Decimal("1600.00") and cats["OCUPAÇÃO"] == Decimal("700.00")
    assert sum(cats.values()) == Decimal("3100.00")


def test_api_do_painel_e_permissoes(cen):
    tid = cen["tenant"]
    url = f"/tenants/{tid}/paineis/fornecedores"
    r = client.get(f"{url}?meses=2026-08", headers=cen["adm"])
    assert r.status_code == 200 and float(r.json()["receita"]["2026-08"]) == 5000.0
    assert client.get(f"{url}/meses", headers=cen["adm"]).json() == ["2026-07", "2026-08"]
    caixa = client.get(f"{url}?meses=2026-08&visao=caixa", headers=cen["adm"])     # sem extrato: vazio, não erro
    assert caixa.status_code == 200 and caixa.json()["visao"] == "caixa" and caixa.json()["linhas"] == []
    assert client.get(f"{url}?meses=2026-13", headers=cen["adm"]).status_code == 422
    gestor = login(criar_usuario("gestor_loja", tid, cen["loja"]))          # dashboards:ler na própria loja
    assert client.get(f"{url}?meses=2026-08", headers=gestor).status_code == 200
    ti = login(criar_usuario("ti_ops", tid))                                 # sem dashboards:ler
    assert client.get(f"{url}?meses=2026-08", headers=ti).status_code == 403
    outro = client.post("/tenants", headers=cen["adm"], json={"rede_codigo": "giraffas", "codigo": f"o{_sufixo()}",
                                                               "razao_social": "Outro"}).json()["id"]
    assert client.get(f"/tenants/{outro}/paineis/fornecedores?meses=2026-08", headers=gestor).status_code == 403


def test_pagina_e_inicio():
    r = client.get("/painel")
    assert r.status_code == 200 and "IN-360" in r.text and "text/html" in r.headers["content-type"]
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/painel"


def test_ponte_de_vendas_espelha_e_e_idempotente(cen):
    cod = cen["codigo"]
    relato = espelhar_vendas(cod, "GSHBH", [{"data": "2026-08-01", "faturamento": "3000.00", "tc": "100"},
                                            {"data": "2026-08-02", "faturamento": "2000.00", "tc": "80"},
                                            {"data": "2026-07-15", "faturamento": "4000.00"}], simular=False)
    assert "0 novos · 0 alterados · 0 removidos · 3 iguais" in relato[0]
    # 02/08 sumiu da origem, 01/08 mudou; 15/07 fica fora do novo intervalo e não é tocado
    relato = espelhar_vendas(cod, "GSHBH", [{"data": "2026-08-01", "faturamento": "3100.00", "tc": "100"},
                                            {"data": "2026-08-03", "faturamento": "50.00"}], simular=False)
    assert "1 novos · 1 alterados · 1 removidos" in relato[0]
    with nova_sessao() as db:
        usar_tenant(db, cen["tenant"])
        d = montar(db, cen["tenant"], [cen["loja"]], ["2026-07", "2026-08"])
    assert d["receita"] == {"2026-07": Decimal("4000.00"), "2026-08": Decimal("3150.00")}
