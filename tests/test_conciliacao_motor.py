"""Passo 5c-3: motor de match banco × GCOM (função pura, sem banco de dados)."""
from datetime import date
from decimal import Decimal

from modules.conciliacao.motor import (BATIDO, INVESTIGAR, SUGERIDO, Debito, Documento, Padrao, conciliar,
                                       numero_base)

D = Decimal
RFG, JM, RIB, KEL, LIVRE = 1, 2, 3, 4, 5
PADROES = {RFG: Padrao("um_para_um", id=11), JM: Padrao("nota_mais_ajuste", id=12),
           RIB: Padrao("agrupado_vencimento", id=13), KEL: Padrao("consolidado_mensal", id=14),
           LIVRE: Padrao("livre", id=15)}


def deb(i, dia, valor, forn):
    return Debito(i, dia, D(valor), forn)


def doc(i, numero, valor, venc, forn, mes=None):
    return Documento(i, numero, D(valor), venc, mes or venc.strftime("%Y-%m"), forn)


def _por_debito(res):
    return {r.debitos[0].id: r for r in res}


def test_numero_base_da_nota_complementar():
    existentes = {"231350", "2313501", "222451"}
    assert numero_base("2313501", existentes) == "231350"
    assert numero_base("231350/1", existentes) == "231350"
    assert numero_base("D222451", existentes) == "222451"
    assert numero_base("222451", existentes) == "222451"
    assert numero_base("9991", existentes) == "9991"          # sem a principal, não corta o "1"


def test_um_para_um_exato_e_centavo_de_diferenca_nao_bate():
    res = conciliar([deb(1, date(2026, 8, 10), "1500.00", RFG), deb(2, date(2026, 8, 12), "800.01", RFG)],
                    [doc(10, "A1", "1500.00", date(2026, 8, 9), RFG), doc(11, "A2", "800.00", date(2026, 8, 12), RFG)],
                    PADROES)
    r = _por_debito(res)
    assert r[1].status == BATIDO and [d.id for d in r[1].documentos] == [10] and r[1].diferenca == D("0.00")
    assert 2 not in r                                             # R$ 0,01 de diferença: não concilia


def test_fora_da_janela_nao_bate():
    res = conciliar([deb(1, date(2026, 8, 20), "1500.00", RFG)],
                    [doc(10, "A1", "1500.00", date(2026, 8, 9), RFG)], PADROES)
    assert res == []


def test_jm_nota_mais_complemento_mesmo_numero_mesmo_com_vencimento_diferente():
    res = conciliar([deb(1, date(2026, 7, 3), "1000.00", JM)],
                    [doc(10, "222451", "700.00", date(2026, 7, 3), JM),
                     doc(11, "2224511", "300.00", date(2026, 6, 19), JM),
                     doc(12, "999999", "1000.00", date(2026, 7, 3), JM, mes="2026-07")], PADROES)
    # o grupo 222451 (700 + 300) e a nota 999999 (1000) empatam: decisão humana
    assert [r.status for r in res] == [INVESTIGAR]
    res = conciliar([deb(1, date(2026, 7, 3), "1000.00", JM)],
                    [doc(10, "222451", "700.00", date(2026, 7, 3), JM),
                     doc(11, "2224511", "300.00", date(2026, 6, 19), JM)], PADROES)
    assert res[0].status == BATIDO and {d.id for d in res[0].documentos} == {10, 11}


def test_jm_pago_em_atraso_separa_multa_e_juros():
    docs = [doc(10, "231350", "800.00", date(2026, 9, 1), JM), doc(11, "2313501", "200.00", date(2026, 9, 1), JM)]
    res = conciliar([deb(1, date(2026, 9, 4), "1030.00", JM)], docs, PADROES)
    assert res[0].status == BATIDO and res[0].acrescimo == D("30.00") and res[0].diferenca == D("30.00")
    # acima de 5% não é atraso: não concilia
    assert conciliar([deb(1, date(2026, 9, 4), "1050.01", JM)], docs, PADROES) == []
    # pago no vencimento com valor maior: não é atraso
    assert conciliar([deb(1, date(2026, 9, 1), "1030.00", JM)], docs, PADROES) == []


def test_ribeiro_soma_por_vencimento():
    res = conciliar([deb(1, date(2026, 8, 7), "330.50", RIB)],
                    [doc(10, "R1", "120.25", date(2026, 8, 7), RIB), doc(11, "R2", "210.25", date(2026, 8, 7), RIB),
                     doc(12, "R3", "99.00", date(2026, 8, 14), RIB)], PADROES)
    assert len(res) == 1 and res[0].status == BATIDO and {d.id for d in res[0].documentos} == {10, 11}


def test_kelminas_mes_inteiro_e_divergencia_visivel():
    notas = [doc(10 + i, f"K{i}", "100.00", date(2026, 7, 3 + i), KEL) for i in range(5)]
    res = conciliar([deb(1, date(2026, 8, 6), "500.00", KEL)], notas, PADROES)
    assert res[0].status == BATIDO and len(res[0].documentos) == 5
    res = conciliar([deb(1, date(2026, 8, 6), "480.00", KEL)], notas, PADROES)
    assert res[0].status == INVESTIGAR and res[0].diferenca == D("-20.00") and "difere" in res[0].nota


def test_sem_padrao_so_sugere_valor_exato_e_unico():
    res = conciliar([deb(1, date(2026, 8, 20), "18308.52", LIVRE), deb(2, date(2026, 8, 20), "55.00", None),
                     deb(3, date(2026, 8, 21), "55.00", None)],
                    [doc(10, "M1", "18308.52", date(2026, 8, 20), None),
                     doc(11, "X1", "55.00", date(2026, 8, 20), None)], PADROES)
    r = _por_debito(res)
    assert r[1].status == SUGERIDO and r[1].documentos[0].id == 10
    assert 2 not in r and 3 not in r                              # 2 débitos de R$ 55 para 1 nota: ninguém


def test_um_debito_nao_entra_em_duas_conciliacoes():
    res = conciliar([deb(1, date(2026, 8, 10), "100.00", RFG)],
                    [doc(10, "A1", "100.00", date(2026, 8, 9), RFG), doc(11, "A2", "100.00", date(2026, 8, 11), RFG)],
                    PADROES)
    assert len(res) == 1 and res[0].status == INVESTIGAR and {d.id for d in res[0].documentos} == {10, 11}
