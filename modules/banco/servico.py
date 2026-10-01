"""Regras do banco: importação idempotente, buracos no extrato (pelo saldo) e resumo mensal."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.banco.extratos import CENTAVO, Extrato, ler, sha256
from modules.banco.models import ContaBancaria, ExtratoImportacao, ExtratoLancamento


@dataclass
class Lacuna:
    conta_id: int
    depois_de: date          # último lançamento conhecido antes do buraco
    antes_de: date           # primeiro lançamento conhecido depois do buraco
    faltando: Decimal        # movimento líquido que não está no extrato (entradas − saídas)


def conta_do_extrato(db: Session, tenant_id: int, ext: Extrato) -> ContaBancaria:
    q = select(ContaBancaria).where(ContaBancaria.tenant_id == tenant_id, ContaBancaria.banco == ext.banco,
                                    ContaBancaria.conta == ext.conta)
    if ext.agencia is not None:          # o extrato do internet banking do Santander não traz a agência
        q = q.where(ContaBancaria.agencia == ext.agencia)
    c = db.scalar(q)
    if c is None:
        c = ContaBancaria(tenant_id=tenant_id, banco=ext.banco, agencia=ext.agencia, conta=ext.conta,
                          apelido=ext.banco, ativo=True)
        db.add(c)
        db.flush()
    return c


def importar_arquivo(db: Session, tenant_id: int, caminho: Path, usuario_id: int | None = None,
                     aceitar_quebras: bool = False) -> str:
    assinatura = sha256(caminho)
    if db.scalar(select(ExtratoImportacao.id).where(ExtratoImportacao.tenant_id == tenant_id,
                                                    ExtratoImportacao.arquivo_sha256 == assinatura)):
        return f"[já importado] {caminho.name}"
    try:
        ext = ler(caminho)
    except ValueError as e:
        return f"[ignorado ] {e}"
    except Exception as e:  # arquivo corrompido ou formato inesperado: relata e segue com os outros
        return f"[ERRO     ] {caminho.name}: {type(e).__name__}: {e}"
    if not ext.linhas:
        return f"[ignorado ] {caminho.name}: sem lançamentos"
    if all(l.saldo is None for l in ext.linhas):
        return _completar_buracos(db, tenant_id, caminho, assinatura, ext, usuario_id)
    if ext.quebras_saldo and not aceitar_quebras:
        return f"[RECUSADO ] {caminho.name}: o saldo não fecha em {ext.quebras_saldo} linha(s)"

    conta = conta_do_extrato(db, tenant_id, ext)
    de, ate = ext.linhas[0].data, ext.linhas[-1].data
    imp = ExtratoImportacao(tenant_id=tenant_id, conta_id=conta.id, arquivo_nome=caminho.name,
                            arquivo_sha256=assinatura, formato=ext.formato, periodo_de=de, periodo_ate=ate,
                            linhas_lidas=len(ext.linhas), saldo_inicial=ext.saldo_inicial,
                            saldo_final=ext.saldo_final, quebras_saldo=ext.quebras_saldo,
                            saldo_confere=ext.quebras_saldo == 0, importado_por=usuario_id)
    db.add(imp)
    db.flush()

    # O mesmo lançamento é reconhecido por data + valor + saldo depois dele: o banco muda o TEXTO do
    # histórico entre exportações (ex.: "TRANSFERENCIA PIX REM" → "PIX RECEBIDO REM"), o saldo não.
    # Sem saldo na linha, vale data + histórico + valor + ocorrência.
    ja = db.scalars(select(ExtratoLancamento).where(ExtratoLancamento.conta_id == conta.id,
                                                    ExtratoLancamento.data >= de, ExtratoLancamento.data <= ate)).all()
    por_saldo = {(l.data, l.valor, l.saldo_informado): l for l in ja if l.saldo_informado is not None}
    por_texto = {(l.data, l.historico, l.valor, l.ocorrencia): l for l in ja}
    ocorrencias_usadas: dict[tuple, set] = defaultdict(set)
    for l in ja:
        ocorrencias_usadas[(l.data, l.historico, l.valor)].add(l.ocorrencia)
    por_dia_banco = defaultdict(int)
    for l in ja:
        por_dia_banco[l.data] += 1
    por_dia_arquivo = defaultdict(int)
    for l in ext.linhas:
        por_dia_arquivo[l.data] += 1

    contagem: dict[tuple, int] = defaultdict(int)
    ordem_no_dia: dict[date, int] = defaultdict(int)
    novas = 0
    for l in ext.linhas:
        ordem_no_dia[l.data] += 1
        base = (l.data, l.historico, l.valor)
        contagem[base] += 1
        if l.saldo is not None:
            atual = por_saldo.get((l.data, l.valor, l.saldo))
        else:
            atual = por_texto.get((*base, contagem[base]))
        if atual is None:
            ocorrencia = contagem[base]
            while ocorrencia in ocorrencias_usadas[base]:      # outro arquivo já usou esse número no dia
                ocorrencia += 1
            ocorrencias_usadas[base].add(ocorrencia)
            db.add(ExtratoLancamento(
                tenant_id=tenant_id, conta_id=conta.id, importacao_id=imp.id, data=l.data,
                ordem=ordem_no_dia[l.data], historico=l.historico, historico_chave=l.historico[:33],
                documento=l.documento, valor=l.valor, natureza="C" if l.valor > 0 else "D",
                saldo_informado=l.saldo, ocorrencia=ocorrencia))
            novas += 1
        elif por_dia_arquivo[l.data] >= por_dia_banco[l.data]:
            # este arquivo tem o dia mais completo: vale a ordem dele (necessária para o saldo corrido)
            atual.ordem, atual.saldo_informado = ordem_no_dia[l.data], l.saldo
    imp.linhas_novas = novas
    db.flush()   # a sessão não tem autoflush: sem isto, o próximo arquivo e a busca de buracos não veem estas linhas
    aviso = f" · ⚠️ {ext.quebras_saldo} quebra(s) de saldo aceitas" if ext.quebras_saldo else ""
    return (f"[importado] {caminho.name}: {ext.banco} {de:%d-%m-%Y} a {ate:%d-%m-%Y} · {len(ext.linhas)} lidas · "
            f"{novas} novas{aviso}")


def _completar_buracos(db: Session, tenant_id: int, caminho: Path, assinatura: str, ext: Extrato,
                       usuario_id: int | None) -> str:
    """Extrato SEM saldo (Santander internet banking) só completa buracos já provados pelo saldo.

    Sem saldo, sem documento e sem o CPF no texto, o lançamento é reconhecido por DATA + VALOR: dia a dia, o que o
    arquivo tem e o banco não tem é o que falta. Só entra se (1) o arquivo contém tudo o que o banco já tem nesses
    dias (senão o arquivo não é confiável: recusa inteiro), (2) o dia cai dentro de um buraco do saldo e (3) a soma
    do que falta no buraco é EXATAMENTE o que o saldo diz que falta. Aí o saldo de cada lançamento novo é recalculado
    e o buraco fecha. No dia em que o buraco termina, os novos vão antes dos existentes (a exportação com saldo
    corta os mais antigos); no dia em que começa, depois."""
    conta = db.scalar(select(ContaBancaria).where(ContaBancaria.tenant_id == tenant_id, ContaBancaria.banco == ext.banco,
                                                  ContaBancaria.conta == ext.conta))
    if conta is None:
        return f"[RECUSADO ] {caminho.name}: extrato sem saldo de uma conta que ainda não existe ({ext.banco} {ext.conta})"
    de, ate = ext.linhas[0].data, ext.linhas[-1].data
    no_banco: dict[date, list[ExtratoLancamento]] = defaultdict(list)
    for l in db.scalars(select(ExtratoLancamento).where(ExtratoLancamento.conta_id == conta.id,
                                                        ExtratoLancamento.data >= de, ExtratoLancamento.data <= ate)
                        .order_by(ExtratoLancamento.data, ExtratoLancamento.ordem)):
        no_banco[l.data].append(l)
    no_arquivo: dict[date, list] = defaultdict(list)
    for l in ext.linhas:
        no_arquivo[l.data].append(l)

    faltam: dict[date, list] = {}
    for dia, linhas in no_arquivo.items():
        if Counter(l.valor for l in no_banco[dia]) - Counter(l.valor for l in linhas):
            return (f"[RECUSADO ] {caminho.name}: em {dia:%d-%m-%Y} o banco tem lançamento que o arquivo não tem "
                    "(arquivo incompleto ou de outra conta)")
        resto = Counter(l.valor for l in linhas) - Counter(l.valor for l in no_banco[dia])
        escolhidas = []
        for l in linhas:                                   # na ordem do arquivo (já cronológica)
            if resto[l.valor] > 0:
                resto[l.valor] -= 1
                escolhidas.append(l)
        if escolhidas:
            faltam[dia] = escolhidas

    imp = ExtratoImportacao(tenant_id=tenant_id, conta_id=conta.id, arquivo_nome=caminho.name, arquivo_sha256=assinatura,
                            formato=ext.formato, periodo_de=de, periodo_ate=ate, linhas_lidas=len(ext.linhas),
                            quebras_saldo=0, saldo_confere=True, importado_por=usuario_id)
    db.add(imp)
    db.flush()
    usadas: dict[tuple, set] = defaultdict(set)
    for ls in no_banco.values():
        for l in ls:
            usadas[(l.data, l.historico, l.valor)].add(l.ocorrencia)
    novas, relato, encaixadas = 0, [], set()
    for b in lacunas(db, conta.id):
        dias = sorted(d for d in faltam if b.depois_de <= d <= b.antes_de)
        if not dias:
            continue
        soma = sum((l.valor for d in dias for l in faltam[d]), Decimal(0))
        if soma != b.faltando or b.depois_de == b.antes_de:
            relato.append(f"buraco {b.depois_de:%d-%m}→{b.antes_de:%d-%m}: o arquivo traz {soma:,.2f}, o saldo pede "
                          f"{b.faltando:,.2f} → não completado")
            continue
        for ponta in (b.depois_de, b.antes_de):            # as pontas do buraco podem estar fora do arquivo
            if ponta not in no_banco:
                no_banco[ponta] = list(db.scalars(select(ExtratoLancamento).where(
                    ExtratoLancamento.conta_id == conta.id, ExtratoLancamento.data == ponta)
                    .order_by(ExtratoLancamento.ordem)))
        saldo = next(l.saldo_informado for l in reversed(no_banco[b.depois_de]) if l.saldo_informado is not None)
        for d in dias:
            antes = d == b.antes_de
            if antes:                                       # abre espaço no começo do dia
                for l in no_banco[d]:
                    l.ordem += len(faltam[d])
            ordem = 0 if antes else max((l.ordem for l in no_banco[d]), default=0)
            for l in faltam[d]:
                ordem += 1
                saldo += l.valor
                oc = 1
                while oc in usadas[(d, l.historico, l.valor)]:
                    oc += 1
                usadas[(d, l.historico, l.valor)].add(oc)
                db.add(ExtratoLancamento(tenant_id=tenant_id, conta_id=conta.id, importacao_id=imp.id, data=d,
                                         ordem=ordem, historico=l.historico, historico_chave=l.historico[:33],
                                         documento=None, valor=l.valor, natureza="C" if l.valor > 0 else "D",
                                         saldo_informado=saldo, ocorrencia=oc))
                novas += 1
            encaixadas.add(d)
        relato.append(f"buraco {b.depois_de:%d-%m}→{b.antes_de:%d-%m} ({b.faltando:,.2f}) completado")
    fora = [l for d, ls in faltam.items() if d not in encaixadas for l in ls]
    if fora:
        relato.append(f"{len(fora)} lançamento(s) fora de buraco do saldo NÃO importados "
                      f"({sum((l.valor for l in fora), Decimal(0)):,.2f})")
        imp.saldo_confere = False
    imp.linhas_novas = novas
    db.flush()
    return f"[importado] {caminho.name}: {ext.banco} sem saldo {de:%d-%m-%Y} a {ate:%d-%m-%Y} · {len(ext.linhas)} lidas · "            f"{novas} novas · " + "; ".join(relato or ["nenhum buraco a completar"])


def lacunas(db: Session, conta_id: int) -> list[Lacuna]:
    """Buracos no extrato: onde o saldo do lançamento não é o anterior + o valor."""
    saida, anterior, data_ant = [], None, None
    for l in db.scalars(select(ExtratoLancamento).where(ExtratoLancamento.conta_id == conta_id)
                        .order_by(ExtratoLancamento.data, ExtratoLancamento.ordem, ExtratoLancamento.id)):
        if l.saldo_informado is None:
            continue
        if anterior is not None and abs(anterior + l.valor - l.saldo_informado) > CENTAVO:
            saida.append(Lacuna(conta_id, data_ant, l.data, l.saldo_informado - l.valor - anterior))
        anterior, data_ant = l.saldo_informado, l.data
    return saida


def resumo_mensal(db: Session, contas: list[ContaBancaria], de: str, ate: str) -> dict:
    """Por conta e por mês (AAAA-MM): saldo inicial, entradas, saídas, saldo final, nº de lançamentos."""
    resultado = {}
    for c in contas:
        meses: dict[str, dict] = {}
        for l in db.scalars(select(ExtratoLancamento).where(ExtratoLancamento.conta_id == c.id)
                            .order_by(ExtratoLancamento.data, ExtratoLancamento.ordem, ExtratoLancamento.id)):
            m = f"{l.data:%Y-%m}"
            if not de <= m <= ate:
                continue
            r = meses.setdefault(m, {"entradas": Decimal(0), "saidas": Decimal(0), "lancamentos": 0,
                                     "saldo_inicial": None, "saldo_final": None})
            if r["saldo_inicial"] is None and l.saldo_informado is not None:
                r["saldo_inicial"] = l.saldo_informado - l.valor
            if l.saldo_informado is not None:
                r["saldo_final"] = l.saldo_informado
            r["entradas" if l.valor > 0 else "saidas"] += l.valor
            r["lancamentos"] += 1
        buracos = [b for b in lacunas(db, c.id) if de <= f"{b.antes_de:%Y-%m}" and f"{b.depois_de:%Y-%m}" <= ate]
        resultado[c.id] = {"conta": {"id": c.id, "banco": c.banco, "apelido": c.apelido, "agencia": c.agencia},
                           "meses": meses,
                           "lacunas": [{"depois_de": b.depois_de, "antes_de": b.antes_de, "faltando": b.faltando}
                                       for b in buracos]}
    return resultado
