"""Extratos novos → IN-360 (roda no Windows, na raiz do projeto):

    py automations\\tools\\ponte_extratos.py

1. COPIA (nunca move nem apaga) os extratos Bradesco/Santander das pastas onde o usuário já os coloca
   para a Gestão, para C:\\giraffas-erp-data\\entrada\\extratos. Arquivo com o mesmo nome não é copiado de novo.
2. Roda o importador na API (`python -m modules.banco.importar`): arquivo já importado é pulado pelo hash,
   lançamento repetido não duplica, arquivo com saldo que não fecha é recusado.
Planilhas "tratado" são ignoradas (não têm saldo). Log: C:\\giraffas-erp-data\\logs\\ponte_extratos.log
"""
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DESTINO = Path(r"C:\giraffas-erp-data\entrada\extratos")
LOG = Path(r"C:\giraffas-erp-data\logs\ponte_extratos.log")
DATALAKE = Path(r"G:\Meu Drive\1-RSIN(holding)\3-Rodiza - Giraffas\Gestao\Giraffas-Datalake\01_entrada")
ORIGENS = [DATALAKE, DATALAKE / "processados", Path(r"C:\Users\rodsa\OneDrive\Documentos\GESTÃO_GIRAFFAS")]
PADRAO = re.compile(r"bradesco|santander", re.IGNORECASE)
EXTENSOES = {".xlsx", ".xls", ".csv"}


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {msg}\n")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    DESTINO.mkdir(parents=True, exist_ok=True)
    copiados = []
    for pasta in ORIGENS:
        if not pasta.exists():
            continue
        for p in pasta.iterdir():
            if (p.is_file() and p.suffix.lower() in EXTENSOES and PADRAO.search(p.name)
                    and "tratado" not in p.name.lower() and not (DESTINO / p.name).exists()):
                shutil.copy2(p, DESTINO / p.name)
                copiados.append(p.name)
    r = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-m", "modules.banco.importar",
                        "--tenant", "rodiza", "/data/entrada/extratos"], cwd=RAIZ, capture_output=True)
    saida = r.stdout.decode("utf-8", "replace")
    importados = [l for l in saida.splitlines() if l.startswith(("[importado]", "[RECUSADO ]", "[ERRO     ]"))]
    print(f"Copiados: {len(copiados)}"); print("\n".join(importados) or "Nenhum extrato novo.")
    if r.returncode != 0:
        erro = r.stderr.decode("utf-8", "replace").strip()
        log(f"ERRO ao importar: {erro[-500:]}")
        print(erro)
        return 1
    log(f"copiados {len(copiados)} · " + (" | ".join(importados) if importados else "nenhum extrato novo"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
