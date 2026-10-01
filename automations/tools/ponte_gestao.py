"""Cópia diária Gestão → IN-360 do faturamento diário (roda no Windows, na raiz do projeto):

    py automations\\tools\\ponte_gestao.py [--simular]

Lê (SÓ LEITURA) database_realizado_dia.csv do Datalake no Google Drive e entrega ao IN-360
(`python -m modules.vendas.ponte` dentro da API). A pasta da Gestão nunca é alterada.
Log: C:\\giraffas-erp-data\\logs\\ponte_gestao.log
"""
import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO = Path(r"G:\Meu Drive\1-RSIN(holding)\3-Rodiza - Giraffas\Gestao\Giraffas-Datalake"
               r"\02_database\database_realizado_dia.csv")
LOG = Path(r"C:\giraffas-erp-data\logs\ponte_gestao.log")
TENANT, LOJA = "rodiza", "GSHBH"


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {msg}\n")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()
    if not ARQUIVO.exists():
        log(f"ERRO: arquivo não encontrado (Google Drive montado?): {ARQUIVO}")
        print(f"ERRO: não achei {ARQUIVO}")
        return 2
    with ARQUIVO.open(encoding="utf-8-sig", newline="") as f:
        linhas = [{k: r.get(k) for k in ("data", "faturamento", "tc", "tm", "adc", "beb", "sob", "origem")}
                  for r in csv.DictReader(f)]
    cmd = ["docker", "compose", "exec", "-T", "api", "python", "-m", "modules.vendas.ponte",
           "--tenant", TENANT, "--loja-sigla", LOJA] + (["--simular"] if a.simular else [])
    r = subprocess.run(cmd, cwd=RAIZ, input=json.dumps(linhas).encode("utf-8"), capture_output=True)
    saida = r.stdout.decode("utf-8", "replace").strip()
    print(saida)
    if r.returncode != 0:
        erro = r.stderr.decode("utf-8", "replace").strip()
        print(erro)
        log(f"ERRO ao gravar no IN-360: {erro[-500:]}")
        return 1
    log(("SIMULACAO " if a.simular else "") + saida.splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
