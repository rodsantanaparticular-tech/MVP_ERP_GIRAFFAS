# Copia os backups do IN-360 (pg_dump diário/semanal/mensal) para o Google Drive.
# O Google Drive para computador (G:) sobe a pasta para a nuvem sozinho.
#
#   Origem : C:\giraffas-erp-data\backups
#   Destino: G:\Meu Drive\1-RSIN(holding)\3-Rodiza - Giraffas\backup in-360
#
# SÓ ACRESCENTA (robocopy sem /PURGE e sem /MIR): se o disco local falhar ou a
# pasta local ficar vazia, a cópia na nuvem continua intacta.
# NUNCA copiar a pasta secrets\ (a erp_master_key não pode ficar junto do backup).
#
# Agendado pela tarefa "IN360_Backup_Drive" (diária, 03:00, roda assim que o PC
# ligar se estava desligado). Rodar na mão:  powershell -File infra\backup\copiar_backup_drive.ps1

$origem  = "C:\giraffas-erp-data\backups"
$destino = "G:\Meu Drive\1-RSIN(holding)\3-Rodiza - Giraffas\backup in-360"
$log     = "C:\giraffas-erp-data\logs\backup_drive.log"

if (-not (Test-Path "G:\Meu Drive")) {
    Add-Content $log "$(Get-Date -Format s) ERRO: Google Drive (G:) nao esta montado. Nada copiado."
    exit 2
}
New-Item -ItemType Directory -Force -Path $destino | Out-Null

# *-latest.sql.gz são links simbólicos do Linux (ilegíveis no Windows) e duplicam os arquivos reais
robocopy $origem $destino /E /XO /XF *-latest.sql.gz /R:3 /W:10 /NP /NDL /LOG+:$log | Out-Null
$rc = $LASTEXITCODE
Add-Content $log "$(Get-Date -Format s) robocopy terminou com codigo $rc (0-7 = ok, 8+ = erro)"
if ($rc -ge 8) { exit 1 } else { exit 0 }
