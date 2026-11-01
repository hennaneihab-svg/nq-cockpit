# Installe la tâche planifiée « NQ Cockpit Alerter » (utilisateur courant, sans admin).
$ErrorActionPreference = "Stop"

$taskName = "NQ Cockpit Alerter"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    $python = Join-Path $repo ".venv\Scripts\python.exe"
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-m nqcockpit.alerts.run" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 3)
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Output "Task '$taskName' installed (every 3 min)."
