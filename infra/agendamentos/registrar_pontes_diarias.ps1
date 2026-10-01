# Registra (ou atualiza) a tarefa "IN360_Pontes_Diarias": cópias diárias SÓ LEITURA para o IN-360
#   1. despesas do Raio-X        (automations\tools\ponte_raiox.py  → log ponte_raiox.log)
#   2. faturamento da Gestão     (automations\tools\ponte_gestao.py → log ponte_gestao.log)
#   3. extratos bancários novos  (automations\tools\ponte_extratos.py → log ponte_extratos.log)
# Diária às 07:30; se o PC estiver desligado nesse horário, roda assim que ligar. Não precisa de admin.
# Substitui a tarefa antiga "IN360_Ponte_RaioX".
#
#   powershell -ExecutionPolicy Bypass -File infra\agendamentos\registrar_pontes_diarias.ps1
#
# Usa schtasks.exe + XML (e não os cmdlets *-ScheduledTask), porque estes dependem do WMI, que falha
# quando o PC está com pouca memória livre (visto em 29/09: "Memória insuficiente", 0x80041006).
# Desligar quando os módulos forem portados:  schtasks /Delete /TN IN360_Pontes_Diarias /F

$ErrorActionPreference = 'Stop'
$raiz = (Resolve-Path "$PSScriptRoot\..\..").Path
$py = (Get-Command py.exe).Source
$comando = "Set-Location '$raiz'; & '$py' automations\tools\ponte_raiox.py; & '$py' automations\tools\ponte_gestao.py; & '$py' automations\tools\ponte_extratos.py"
$argumentos = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$comando`""
$usuario = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>IN-360: copias diarias SO LEITURA (despesas do Raio-X + faturamento da Gestao + extratos). Logs em C:\giraffas-erp-data\logs</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-09-30T07:30:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>$usuario</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <StartWhenAvailable>true</StartWhenAvailable>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT20M</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>powershell.exe</Command><Arguments>$([System.Security.SecurityElement]::Escape($argumentos))</Arguments></Exec>
  </Actions>
</Task>
"@
$arquivo = Join-Path $env:TEMP "IN360_Pontes_Diarias.xml"
[System.IO.File]::WriteAllText($arquivo, $xml, [System.Text.Encoding]::Unicode)
schtasks.exe /Create /TN "IN360_Pontes_Diarias" /XML $arquivo /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw "schtasks falhou ($LASTEXITCODE): a tarefa NAO foi criada e a antiga NAO foi removida." }
Remove-Item $arquivo
$antiga = cmd.exe /c "schtasks /Query /TN IN360_Ponte_RaioX >nul 2>&1 && echo sim"
if ($antiga -eq "sim") { schtasks.exe /Delete /TN "IN360_Ponte_RaioX" /F | Out-Null; Write-Host "Tarefa antiga IN360_Ponte_RaioX removida." }
Write-Host "Tarefa IN360_Pontes_Diarias registrada (diaria 07:30)."
