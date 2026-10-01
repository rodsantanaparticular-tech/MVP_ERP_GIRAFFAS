"""Passo 5: leitura de extratos (Bradesco/Santander), importação idempotente, buracos e API do banco."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import modules.models  # noqa: F401
from api.main import app
from core.db import nova_sessao, usar_tenant
from modules.banco.extratos import ler
from modules.banco.models import ContaBancaria, ExtratoLancamento
from modules.banco.router import tipo_lancamento
from modules.banco.servico import importar_arquivo, lacunas, resumo_mensal
from tests.test_etapa1_seguranca_cofre import _sufixo, criar_usuario, login

client = TestClient(app)
D = Decimal


def _xlsx(caminho, linhas):
    wb = Workbook()
    for r in linhas:
        wb.active.append(r)
    wb.save(caminho)
    return caminho


def _bradesco(caminho, saldo_ini, lancs, agencia="1234", conta="56789-0"):
    """lancs = [(dd/mm/aaaa, histórico, valor)] em ordem; saldo calculado; + seção 'Últimos Lançamentos'."""
    linhas = [[None], [None, "Bradesco Net Empresa"], [None], [f"Extrato de: Agência: {agencia}  Conta: {conta}"], [None],
              ["Data", "Lançamento", "Dcto.", "Crédito (R$)", "Débito (R$)", "Saldo (R$)"],
              ["31/07/2026", "SALDO ANTERIOR", None, None, None, f"{saldo_ini:.2f}".replace(".", ",")]]
    saldo = saldo_ini
    for d, h, v in lancs:
        saldo += v
        cred = f"{v:.2f}".replace(".", ",") if v > 0 else None
        deb = f"{-v:.2f}".replace(".", ",") if v < 0 else None
        linhas.append([d, h, "123", cred, deb, f"{saldo:.2f}".replace(".", ",")])
    linhas += [["Total", None, None, None, None, None], [None], ["Últimos Lançamentos"],
               ["Data", "Lançamento", "Dcto.", "Crédito (R$)", "Débito (R$)", "Saldo (R$)"],
               ["25/09/2026", "NAO PODE ENTRAR", "9", "999,00", None, "1,00"]]
    return _xlsx(caminho, linhas)


def _santander(caminho, lancs, saldo_ini):
    """lancs em ordem cronológica; o arquivo sai do mais NOVO para o mais antigo, como o banco exporta."""
    saldo, corpo = saldo_ini, []
    for d, h, v in lancs:
        saldo += v
        corpo.append([d, h, "0", v, saldo])
    return _xlsx(caminho, [["AGENCIA", "4321", "CONTA", "130000001"], [None],
                           ["Data", "Histórico", "Documento", "Valor (R$)", "Saldo (R$)"]] + corpo[::-1])


def test_leitura_bradesco_para_no_total_e_le_debitos(tmp_path):
    ext = ler(_bradesco(tmp_path / "Bradesco_ago.xlsx", Decimal("100.00"),
                        [("01/08/2026", "PIX RECEBIDO CIELO", Decimal("50.00")),
                         ("01/08/2026", "PAGTO ELETRON COBRANCA RFG", Decimal("-30.00"))]))
    assert (ext.banco, ext.agencia, ext.conta) == ("Bradesco", "1234", "56789-0")
    assert [l.historico for l in ext.linhas] == ["PIX RECEBIDO CIELO", "PAGTO ELETRON COBRANCA RFG"]
    assert ext.linhas[1].valor == Decimal("-30.00") and ext.saldo_inicial == Decimal("100.00")
    assert ext.saldo_final == Decimal("120.00") and ext.quebras_saldo == 0


def test_leitura_bradesco_csv(tmp_path):
    csv = ("\n;Extrato de: Agência: 1234  Conta: 56789-0\nData;Lançamento;Dcto.;Crédito (R$);Débito (R$);Saldo (R$)\n"
           "31/07/2026;SALDO ANTERIOR;;;;10,00\n01/08/2026;TARIFA BANCARIA;1;;2,50;7,50\nTotal;;;;;\n")
    p = tmp_path / "Bradesco_x.CSV"
    p.write_bytes(csv.replace("\n", "\r\r\n").encode("latin1"))   # quebras mistas, como o Bradesco exporta
    ext = ler(p)
    assert ext.linhas[0].valor == Decimal("-2.50") and ext.quebras_saldo == 0


def test_leitura_santander_inverte_para_ordem_cronologica(tmp_path):
    ext = ler(_santander(tmp_path / "santander_a.xlsx", [("01/08/2026", "PIX RECEBIDO  111", Decimal("10")),
                                                         ("02/08/2026", "TARIFA PIX", Decimal("-1"))], Decimal("5")))
    assert ext.banco == "Santander" and [l.data.day for l in ext.linhas] == [1, 2]
    assert ext.linhas[0].historico == "PIX RECEBIDO 111"      # espaços duplos normalizados
    assert ext.quebras_saldo == 0 and ext.saldo_inicial == Decimal("5.00")


def test_tratado_e_saldo_quebrado_nao_entram(tmp_path):
    tratado = _xlsx(tmp_path / "15_Bradesco_tratado.xlsx", [["Data", "Lançamento", "Dcto.", "Movimentação", "Descrição",
                                                             "Classificação", "Fornecedor"]])
    with pytest.raises(ValueError, match="TRATADA"):
        ler(tratado)


@pytest.fixture(scope="module")
def cen():
    adm = login(criar_usuario("plataforma_admin"))
    tid = client.post("/tenants", headers=adm, json={"rede_codigo": "giraffas", "codigo": f"b{_sufixo()}",
                                                     "razao_social": "Cliente Banco"}).json()["id"]
    loja = client.post(f"/tenants/{tid}/lojas", headers=adm, json={"nome": "Loja", "filial_sigla": "L1"}).json()["id"]
    return {"adm": adm, "tenant": tid, "loja": loja}


def test_importacao_idempotente_sobreposicao_e_buraco(cen, tmp_path):
    tid = cen["tenant"]
    ago = _bradesco(tmp_path / "Bradesco_ago.xlsx", Decimal("100"), [
        ("01/08/2026", "PIX RECEBIDO CIELO", Decimal("50")), ("01/08/2026", "PIX RECEBIDO CIELO", Decimal("50")),
        ("02/08/2026", "PAGTO ELETRON COBRANCA RFG", Decimal("-80"))])
    # 2º arquivo sobrepõe 02/08 e segue; 3º arquivo pula 03–04/08 (buraco de +40 líquido)
    # (o banco trocou o TEXTO do 02/08 entre as exportações; data + valor + saldo continuam iguais)
    ago2 = _bradesco(tmp_path / "Bradesco_ago2.xlsx", Decimal("200"), [
        ("02/08/2026", "PAGAMENTO COBRANCA RFG", Decimal("-80")), ("03/08/2026", "TARIFA BANCARIA", Decimal("-5"))])
    ago3 = _bradesco(tmp_path / "Bradesco_ago3.xlsx", Decimal("155"), [("05/08/2026", "PIX RECEBIDO CIELO", Decimal("20"))])
    quebrado = tmp_path / "Bradesco_quebrado.xlsx"
    _xlsx(quebrado, [["Extrato de: Agência: 1234  Conta: 56789-0"],
                     ["Data", "Lançamento", "Dcto.", "Crédito (R$)", "Débito (R$)", "Saldo (R$)"],
                     ["31/07/2026", "SALDO ANTERIOR", None, None, None, "10,00"],
                     ["06/08/2026", "PIX RECEBIDO", "1", "5,00", None, "999,00"]])
    with nova_sessao() as db:
        usar_tenant(db, tid)
        r = [importar_arquivo(db, tid, p) for p in (ago, ago2, ago3, quebrado)]
        assert r[0].startswith("[importado]") and "3 novas" in r[0]
        assert "1 novas" in r[1]                                   # 02/08 não duplicou
        assert r[3].startswith("[RECUSADO ]")
        assert importar_arquivo(db, tid, ago).startswith("[já importado]")
        conta = db.scalar(__import__("sqlalchemy").select(ContaBancaria).where(ContaBancaria.tenant_id == tid))
        buracos = lacunas(db, conta.id)
        assert len(buracos) == 1 and buracos[0].faltando == Decimal("40.00")
        assert (buracos[0].depois_de.day, buracos[0].antes_de.day) == (3, 5)
        res = resumo_mensal(db, [conta], "2026-08", "2026-08")[conta.id]["meses"]["2026-08"]
        assert res["entradas"] == Decimal("120.00") and res["saidas"] == Decimal("-85.00")
        assert res["saldo_inicial"] == Decimal("100.00") and res["saldo_final"] == Decimal("175.00")
        db.commit()


def test_api_do_banco_e_permissoes(cen):
    tid = cen["tenant"]
    assert client.get(f"/tenants/{tid}/banco/contas", headers=cen["adm"]).json()[0]["lancamentos"] == 5
    r = client.get(f"/tenants/{tid}/banco/resumo?de=2026-08&ate=2026-08", headers=cen["adm"]).json()
    assert len(r[0]["lacunas"]) == 1
    d = client.get(f"/tenants/{tid}/banco/lancamentos?mes=2026-08&tipo=saidas", headers=cen["adm"]).json()
    assert d["total_linhas"] == 2 and {g["tipo"] for g in d["grupos"]} == {"PAGTO ELETRON COBRANCA RFG", "TARIFA BANCARIA"}
    franq = login(criar_usuario("franqueado_admin", tid))
    assert client.get(f"/tenants/{tid}/banco/contas", headers=franq).status_code == 200
    gestor = login(criar_usuario("gestor_loja", tid, cen["loja"]))            # sem banco:ler
    assert client.get(f"/tenants/{tid}/banco/contas", headers=gestor).status_code == 403
    outro = client.post("/tenants", headers=cen["adm"], json={"rede_codigo": "giraffas", "codigo": f"x{_sufixo()}",
                                                               "razao_social": "Outro"}).json()["id"]
    assert client.get(f"/tenants/{outro}/banco/contas", headers=franq).status_code == 403
    assert client.get("/painel/banco").status_code == 200


def test_tipo_lancamento():
    assert tipo_lancamento("PIX RECEBIDO  14349745610") == "PIX RECEBIDO"
    assert tipo_lancamento("TED-TRANSF ELET DISPON REMET.RODRIGO") == "TED-TRANSF ELET DISPON REMET.RODRIGO"


def _santander_ib(caminho, conta, lancs):
    """Extrato do internet banking do Santander: sem saldo, data por extenso, do mais novo para o mais antigo."""
    dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
             "novembro", "dezembro"]
    corpo = []
    for d, h, v in reversed(lancs):
        dt = __import__("datetime").datetime.strptime(d, "%d/%m/%Y")
        corpo.append([f"{dias[dt.weekday()]}, {dt.day:02d} de {meses[dt.month - 1]} de {dt.year}", h,
                      float(v) if v > 0 else 0, float(-v) if v < 0 else 0])
    return _xlsx(caminho, [["EXTRATO DE CONTA CORRENTE"], [None], ["EMPRESA LTDA", None, f"Conta: {conta}"], [None],
                           ["Tipo de lançamento: Todos", None, "Extrato de 01/08/2026 a 31/08/2026"],
                           ["Data", "Descrição", "Crédito (R$)", "Débito (R$)"]] + corpo + [[None, "TOTAL", 0, 0]])


def test_extrato_sem_saldo_so_completa_buraco_provado(cen, tmp_path):
    tid = cen["tenant"]
    # conta Santander com buraco: 03/08 fecha em 110; 05/08 começa como se o saldo fosse 120 (faltam +10)
    a = _santander(tmp_path / "santander_a.xlsx", [("01/08/2026", "PIX RECEBIDO 111", D("1")),
                                                   ("03/08/2026", "PIX RECEBIDO 222", D("9"))], D("100"))
    b = _santander(tmp_path / "santander_b.xlsx", [("05/08/2026", "PIX RECEBIDO 333", D("5")),
                                                   ("06/08/2026", "TARIFA PIX", D("-1"))], D("120"))
    ib = [("01/08/2026", "PIX RECEBIDO", D("1")), ("03/08/2026", "PIX RECEBIDO", D("9")),
          ("04/08/2026", "PIX RECEBIDO", D("7")),                          # dia inteiro que faltava
          ("05/08/2026", "PIX RECEBIDO", D("3")),                          # manhã cortada da exportação
          ("05/08/2026", "PIX RECEBIDO", D("5")), ("06/08/2026", "TARIFA PIX", D("-1"))]
    errado = _santander_ib(tmp_path / "ib_errado.xlsx", "13000000-1", ib[:3] + ib[4:])        # só +7: não fecha
    incompleto = _santander_ib(tmp_path / "ib_incompleto.xlsx", "13000000-1", ib[:4] + ib[5:])  # falta o +5 de 05/08
    certo = _santander_ib(tmp_path / "ib_certo.xlsx", "13000000-1", ib[2:])   # começa DEPOIS do início do buraco
    with nova_sessao() as db:
        usar_tenant(db, tid)
        for p in (a, b):
            assert importar_arquivo(db, tid, p).startswith("[importado]")
        conta = db.scalar(__import__("sqlalchemy").select(ContaBancaria).where(
            ContaBancaria.tenant_id == tid, ContaBancaria.banco == "Santander"))
        assert [x.faltando for x in lacunas(db, conta.id)] == [D("10.00")]
        r = importar_arquivo(db, tid, errado)
        assert "0 novas" in r and "não completado" in r
        assert importar_arquivo(db, tid, incompleto).startswith("[RECUSADO ]")
        r = importar_arquivo(db, tid, certo)
        assert "2 novas" in r and "completado" in r, r
        assert lacunas(db, conta.id) == []                                  # o buraco fechou
        dia5 = db.scalars(__import__("sqlalchemy").select(ExtratoLancamento).where(
            ExtratoLancamento.conta_id == conta.id, ExtratoLancamento.data == __import__("datetime").date(2026, 8, 5))
            .order_by(ExtratoLancamento.ordem)).all()
        assert [(l.valor, l.saldo_informado) for l in dia5] == [(D("3.00"), D("120.00")), (D("5.00"), D("125.00"))]
        assert importar_arquivo(db, tid, certo).startswith("[já importado]")
        db.commit()
