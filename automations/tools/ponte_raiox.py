"""Cópia diária Raio-X → IN-360 (roda no Windows, na raiz do projeto):

    py automations\\tools\\ponte_raiox.py              # espelha
    py automations\\tools\\ponte_raiox.py --simular    # mostra o que faria, sem gravar

1. Lê as despesas do banco do Raio-X (contêiner in-360-giraffas-db-1) numa sessão
   SOMENTE LEITURA (default_transaction_read_only): o Raio-X nunca é alterado e
   nenhuma senha dele é usada (psql pelo socket local do próprio contêiner).
2. Entrega o JSON ao IN-360: `python -m modules.raiox_dre.ponte` dentro da API.

Agendado pela tarefa "IN360_Ponte_RaioX" (infra/agendamentos/registrar_ponte_raiox.ps1).
Log: C:\\giraffas-erp-data\\logs\\ponte_raiox.log
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LOG = Path(r"C:\giraffas-erp-data\logs\ponte_raiox.log")
CONTEINER_RAIOX = "in-360-giraffas-db-1"
BANCO_RAIOX = "in360giraffas"
TENANT = "rodiza"

EXPORTA = """
SELECT coalesce(json_agg(json_build_object(
    'loja_nome', l.nome, 'mes', d.mes, 'id_original', d.id_original, 'doc', d.doc, 'valor', d.valor,
    'venc', d.venc, 'entrada', d.entrada, 'fornecedor', d.fornecedor, 'desembolso', d.desembolso,
    'sub', d.sub, 'status_gcom', d.status_gcom, 'observacoes_gcom', d.observacoes_gcom,
    'observacoes_lida_em', d.observacoes_lida_em, 'data_pagamento', d.data_pagamento,
    'sub_itens', d.sub_itens) ORDER BY d.mes, d.id_original), '[]'::json)
FROM despesas d JOIN lojas l ON l.id = d.loja_id
"""


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {msg}\n")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()

    exp = subprocess.run(
        ["docker", "exec", "-i", CONTEINER_RAIOX, "psql", "-U", BANCO_RAIOX, "-d", BANCO_RAIOX,
         "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1",
         "-c", "SET default_transaction_read_only = on", "-c", EXPORTA],
        capture_output=True)
    if exp.returncode != 0:
        erro = exp.stderr.decode("utf-8", "replace").strip()
        log(f"ERRO ao ler o Raio-X: {erro}")
        print(f"ERRO ao ler o Raio-X (o contêiner {CONTEINER_RAIOX} está rodando?):\n{erro}")
        return 1

    cmd = ["docker", "compose", "exec", "-T", "api", "python", "-m", "modules.raiox_dre.ponte", "--tenant", TENANT]
    if a.simular:
        cmd.append("--simular")
    imp = subprocess.run(cmd, cwd=RAIZ, input=exp.stdout, capture_output=True)
    saida = imp.stdout.decode("utf-8", "replace").strip()
    print(saida)
    if imp.returncode != 0:
        erro = imp.stderr.decode("utf-8", "replace").strip()
        print(erro)
        log(f"ERRO ao gravar no IN-360: {erro[-500:]}")
        return 1
    log(("SIMULACAO " if a.simular else "") + saida.splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
