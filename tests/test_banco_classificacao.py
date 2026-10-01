"""Passo 5c: favorecido/classificação do extrato (planilha → regras → transferências entre contas)."""
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import modules.models  # noqa: F401
from api.main import app
from core.db import nova_sessao, usar_tenant
from modules.banco.classificacao import (TRANSFERENCIA, Dicionario, classificar, chave, ler_planilha,
                                         semear_da_planilha)
from modules.banco.models import ContaBancaria, ExtratoLancamento, ExtratoRegra
from modules.banco.servico import importar_arquivo
from modules.pagamentos.models import Fornecedor
from tests.test_banco import _bradesco, _santander, _xlsx
from tests.test_etapa1_seguranca_cofre import _sufixo, criar_usuario, login

client = TestClient(app)
D = Decimal


def test_chave_padroniza_pix_e_espacos():
    assert chave("TRANSFERENCIA PIX DES: KAMILA RAMOS DA SILVA 01/03") == chave("PIX ENVIADO DES: KAMILA RAMOS DA SILVA 02/05")
    assert chave("PAGTO ELETRON  COBRANCA GIRAFFAS") == "PAGTO ELETRON COBRANCA GIRAFFAS"
    assert len(chave("PIX ENVIADO DES: RODRIGO SANT ANA DE SOUZA")) == 33
    assert chave("PIX ENVIADO DES: ANA 04/08") == chave("TRANSFERENCIA PIX DES: ANA 20/09") == "PIX ENVIADO DES: ANA"


@pytest.fixture(scope="module")
def cen(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("classif")
    adm = login(criar_usuario("plataforma_admin"))
    tid = client.post("/tenants", headers=adm, json={"rede_codigo": "giraffas", "codigo": f"c{_sufixo()}",
                                                     "razao_social": "Padaria Modelo Ltda"}).json()["id"]
    brad = _bradesco(tmp / "Bradesco_ago.xlsx", D("1000"), [
        ("03/08/2026", "PAGTO ELETRON  COBRANCA GIRAFFAS", D("-300")),      # royalties
        ("04/08/2026", "PAGTO ELETRON  COBRANCA GIRAFFAS", D("-200")),      # fundo de marketing
        ("04/08/2026", "TRANSFERENCIA PIX DES: FULANA DE TAL 04/08", D("-150")),
        ("05/08/2026", "PAGTO ELETRON  COBRANCA RFG COMERCIO", D("-90")),
        ("06/08/2026", "PIX RECEBIDO REM: PADARIA MODELO 06/08", D("500")),  # vem do Santander
        ("06/08/2026", "PIX RECEBIDO REM: PADARIA MODELO 06/08", D("37")),   # venda repassada
        ("07/08/2026", "PAGTO ELETRON  COBRANCA RIBEIROS LEGUMES", D("-55")),
        ("20/09/2026", "PIX ENVIADO DES: FULANA DE TAL 20/09", D("-160")),   # depois da planilha
        ("21/09/2026", "PAGTO ELETRON  COBRANCA GIRAFFAS", D("-310")),
        ("22/09/2026", "TARIFA BANCARIA NOVA", D("-5"))])
    sant = _santander(tmp / "santander_ago.xlsx", [("04/08/2026", "PIX RECEBIDO 111", D("600")),
                                                  ("05/08/2026", "PIX ENVIADO GIRAFFAS", D("-500"))], D("10"))
    planilha = _xlsx(tmp / "15_Bradesco_tratado.xlsx", [
        ["Data", "Lançamento", "Dcto.", "Movimentação", "Descrição", "Classificação", "Fornecedor"],
        ["03/08/2026", "PAGTO ELETRON  COBRANCA GIRAFFAS", "1", -300, "DEBITO", "ROYALTIES", "GIRAFFAS"],
        ["04/08/2026", "PAGTO ELETRON  COBRANCA GIRAFFAS", "1", -200, "DEBITO", "FUNDO DE MKT", "Giraffas"],
        ["04/08/2026", "TRANSFERENCIA PIX DES: FULANA DE TAL 04/08", "1", -150, "DEBITO", "FOLHA", "Fulana"],
        ["05/08/2026", "PAGTO ELETRON  COBRANCA RFG COMERCIO", "1", -90, "DEBITO", "INSUMO", "MB"],
        ["06/08/2026", "PIX RECEBIDO REM: PADARIA MODELO 06/08", "1", 500, "CREDITO", "PIX", "PADARIA"],
        ["06/08/2026", "PIX RECEBIDO REM: PADARIA MODELO 06/08", "1", 37, "CREDITO", "PIX", "PADARIA"],
        ["07/08/2026", "LINHA QUE NAO EXISTE NO EXTRATO", "1", -1, "DEBITO", "X", "Y"],
        # exportação antiga sem o favorecido: classificada às cegas; vale para a linha, não ensina regra
        ["07/08/2026", "PAGTO ELETRON  COBRANCA", "1", -55, "DEBITO", "DESPESA", "DIVERSOS"]])
    dic_arq = tmp / "dic.json"
    dic_arq.write_text(json.dumps({"grafias": {"FULANA": "FULANA DE TAL"}, "classificacoes": {"FUNDO DE MKT": "FUNDO MKT"},
                                   "fornecedor_crm": {"MB": "RFG", "GIRAFFAS": "Franqueadora", "OUTRO": "Nao Existe"}}),
                       encoding="utf-8")
    with nova_sessao() as db:
        usar_tenant(db, tid)
        for p in (brad, sant):
            assert importar_arquivo(db, tid, p).startswith("[importado]")
        db.add_all([Fornecedor(tenant_id=tid, nome="RFG", apelidos=[], ativo=True),
                    Fornecedor(tenant_id=tid, nome="Franqueadora", apelidos=[], ativo=True)])
        db.commit()
    return {"adm": adm, "tenant": tid, "planilha": planilha, "dic": Dicionario.ler(dic_arq)}


def _linhas(db, tid):
    contas = {c.id: c.banco for c in db.scalars(select(ContaBancaria).where(ContaBancaria.tenant_id == tid))}
    return {(contas[l.conta_id], l.data.isoformat(), l.valor): l
            for l in db.scalars(select(ExtratoLancamento).where(ExtratoLancamento.tenant_id == tid))}


def test_semente_regras_e_transferencias(cen):
    tid, dic = cen["tenant"], cen["dic"]
    with nova_sessao() as db:
        usar_tenant(db, tid)
        brad = db.scalar(select(ContaBancaria).where(ContaBancaria.tenant_id == tid, ContaBancaria.banco == "Bradesco"))
        r = semear_da_planilha(db, tid, brad, ler_planilha(cen["planilha"], dic), dic)
        assert (r.linhas_planilha, r.pareadas, len(r.sem_par), len(r.texto_diferente)) == (8, 7, 1, 1)
        assert not db.scalar(select(ExtratoRegra).where(ExtratoRegra.tenant_id == tid,
                                                        ExtratoRegra.padrao_texto.like("%RIBEIROS%")))
        assert r.fornecedores_faltando == ["Nao Existe"]
        classificar(db, tid)
        db.commit()

        L = _linhas(db, tid)
        forn = {f.nome: f.id for f in db.scalars(select(Fornecedor).where(Fornecedor.tenant_id == tid))}
        # planilha, linha a linha (grafia e classificação normalizadas; fornecedor do CRM ligado)
        roy, fmkt = L[("Bradesco", "2026-08-03", D("-300.00"))], L[("Bradesco", "2026-08-04", D("-200.00"))]
        assert (roy.favorecido, roy.classificacao, roy.classificacao_origem) == ("GIRAFFAS", "ROYALTIES", "planilha")
        assert (fmkt.favorecido, fmkt.classificacao, fmkt.fornecedor_id) == ("GIRAFFAS", "FUNDO MKT", forn["Franqueadora"])
        assert L[("Bradesco", "2026-08-05", D("-90.00"))].fornecedor_id == forn["RFG"]
        # regra aprendida: o boleto da franqueadora não decide a classificação; o Pix da Fulana decide
        gir = L[("Bradesco", "2026-09-21", D("-310.00"))]
        assert (gir.favorecido, gir.classificacao, gir.classificacao_origem) == ("GIRAFFAS", None, "aprendida")
        ful = L[("Bradesco", "2026-09-20", D("-160.00"))]       # texto novo do banco ("PIX ENVIADO DES:")
        assert (ful.favorecido, ful.classificacao, ful.classificacao_origem) == ("FULANA DE TAL", "FOLHA", "aprendida")
        assert L[("Bradesco", "2026-09-22", D("-5.00"))].favorecido is None          # sem regra: pendente
        # transferência: provada pelo par, vence a planilha ("PIX"); a venda de R$ 37 continua venda
        s, e = L[("Santander", "2026-08-05", D("-500.00"))], L[("Bradesco", "2026-08-06", D("500.00"))]
        assert s.classificacao == e.classificacao == TRANSFERENCIA
        assert (s.favorecido, e.favorecido, e.classificacao_origem) == ("Bradesco", "Santander", "sistema")
        assert L[("Bradesco", "2026-08-06", D("37.00"))].classificacao == "PIX"
        assert L[("Santander", "2026-08-04", D("600.00"))].favorecido is None

        # humano manda: classificação manual não é tocada numa nova rodada; e a rodada é idempotente
        ful.classificacao, ful.classificacao_origem = "ADIANTAMENTO", "manual"
        db.commit()
        n_regras = db.scalar(select(__import__("sqlalchemy").func.count()).select_from(ExtratoRegra)
                             .where(ExtratoRegra.tenant_id == tid))
        r2 = semear_da_planilha(db, tid, brad, ler_planilha(cen["planilha"], dic), dic)
        classificar(db, tid)
        db.commit()
        assert r2.regras_novas == 0
        assert db.scalar(select(__import__("sqlalchemy").func.count()).select_from(ExtratoRegra)
                         .where(ExtratoRegra.tenant_id == tid)) == n_regras
        L = _linhas(db, tid)
        assert L[("Bradesco", "2026-09-20", D("-160.00"))].classificacao == "ADIANTAMENTO"
        assert L[("Bradesco", "2026-08-06", D("500.00"))].classificacao == TRANSFERENCIA


def test_api_mostra_favorecido(cen):
    d = client.get(f"/tenants/{cen['tenant']}/banco/lancamentos?mes=2026-08&tipo=saidas", headers=cen["adm"]).json()
    por_valor = {float(l["valor"]): l for l in d["lancamentos"]}
    assert por_valor[-300]["favorecido"] == "GIRAFFAS" and por_valor[-300]["classificacao"] == "ROYALTIES"
    assert por_valor[-500]["classificacao"] == TRANSFERENCIA


def test_regras_manuais_categorias_e_visao_caixa(cen, tmp_path):
    from pathlib import Path

    from modules.banco.classificacao import gravar_categorias, gravar_regras_manuais
    tid, adm = cen["tenant"], cen["adm"]
    dic_arq = tmp_path / "dic_manual.json"
    dic_arq.write_text(json.dumps({"regras_manuais": [
        {"padrao": "^PIX RECEBIDO \d+$", "tipo": "regex", "natureza": "C", "favorecido": "CLIENTE PIX", "classificacao": "PIX"}]}),
        encoding="utf-8")
    seed = Path(__file__).resolve().parents[1] / "database" / "seeds" / "categorias_caixa_rodiza.json"
    with nova_sessao() as db:
        usar_tenant(db, tid)
        assert gravar_regras_manuais(db, tid, Dicionario.ler(dic_arq)) == 1
        assert gravar_categorias(db, tid, seed) == gravar_categorias(db, tid, seed) > 40     # idempotente
        classificar(db, tid)
        db.commit()
        assert _linhas(db, tid)[("Santander", "2026-08-04", D("600.00"))].favorecido == "CLIENTE PIX"

    assert client.get(f"/tenants/{tid}/paineis/fornecedores/meses?visao=caixa", headers=adm).json() == ["2026-08", "2026-09"]
    d = client.get(f"/tenants/{tid}/paineis/fornecedores?meses=2026-08&meses=2026-09&visao=caixa", headers=adm).json()
    cat = {c["categoria"]: {m: float(v) for m, v in c["valores"].items()} for c in d["categorias"]}
    assert cat["ROYALTIES"]["2026-08"] == 300 and cat["FUNDO DE MARKETING"]["2026-08"] == 200
    assert cat["PESSOAL"] == {"2026-08": 150, "2026-09": 160}          # FOLHA (planilha) e ADIANTAMENTO (manual)
    assert cat["INSUMOS"]["2026-08"] == 90
    # boleto da franqueadora sem classe: royalties OU fundo mkt → categorias diferentes → a classificar; tarifa sem regra idem
    assert cat["A CLASSIFICAR"]["2026-09"] == 315 and d["categorias"][-1]["categoria"] == "A CLASSIFICAR"
    assert {float(v) for v in d["total_despesas"].values()} == {795, 475}
    assert cat["DESPESA ADMINISTRATIVAS"]["2026-08"] == 55
    assert float(d["receita"]["2026-08"]) == 637                         # Pix de venda 37 + Pix de cliente 600
    fora = {b["categoria"]: float(b["valores"]["2026-08"]) for b in d["fora_dre"]}
    assert fora == {"TRANSFERÊNCIA ENTRE CONTAS": 0}                    # +500 numa conta, −500 na outra
    rfg = next(l for l in d["linhas"] if l["fornecedor"] == "RFG")
    assert rfg["crm_id"] and rfg["documentos"] == 1

    # sem banco:ler não vê a visão caixa (mas continua vendo a competência)
    loja = client.post(f"/tenants/{tid}/lojas", headers=adm, json={"nome": "Loja", "filial_sigla": "L1"}).json()["id"]
    gestor = login(criar_usuario("gestor_loja", tid, loja))
    assert client.get(f"/tenants/{tid}/paineis/fornecedores?meses=2026-08&visao=caixa", headers=gestor).status_code == 403
    assert client.get(f"/tenants/{tid}/paineis/fornecedores/meses?visao=caixa", headers=gestor).status_code == 403
    assert client.get(f"/tenants/{tid}/paineis/fornecedores?meses=2026-08", headers=gestor).status_code == 200


def test_calendario_da_franqueadora_com_as_datas_reais():
    from datetime import date

    from modules.banco.classificacao import classe_pelo_calendario
    cal = [{"classificacao": "REFIN", "valores": ["2419.16", "1747.35"], "dia": 15},
           {"classificacao": "ROYALTIES", "dia": 20}, {"classificacao": "FUNDO MKT", "dia": "ultimo"}]
    casos = {  # (data do débito no banco, valor): classe esperada
        (date(2025, 12, 18), "-2419.16"): "REFIN", (date(2026, 8, 17), "-1747.35"): "REFIN",
        (date(2025, 12, 22), "-11852.89"): "ROYALTIES",     # 20/12 sábado → segunda
        (date(2025, 12, 29), "-6905.91"): "FUNDO MKT",      # pago antes do último dia
        (date(2026, 2, 2), "-10126.58"): "FUNDO MKT",       # 31/01 sábado → 02/02
        (date(2026, 3, 20), "-8990.89"): "ROYALTIES",       # e-mail: "BOLETO ROYALTIES - VENCIMENTO 20/03/2026"
        (date(2026, 3, 31), "-5322.60"): "FUNDO MKT",
        (date(2026, 5, 4), "-6118.83"): "FUNDO MKT",        # 30/04 → 04/05 (feriado de 1º de maio + fim de semana)
        (date(2026, 6, 22), "-11071.78"): "ROYALTIES",
        (date(2026, 7, 20), "-9679.90"): "ROYALTIES", (date(2026, 7, 31), "-5807.94"): "FUNDO MKT",
        (date(2026, 8, 20), "-13903.92"): "ROYALTIES", (date(2026, 9, 21), "-11698.40"): "ROYALTIES",
        (date(2026, 9, 9), "-500.00"): None,                # fora de qualquer janela: fica para humano
    }
    for (d, v), esperado in casos.items():
        assert classe_pelo_calendario(d, D(v), cal) == esperado, (d, v)
