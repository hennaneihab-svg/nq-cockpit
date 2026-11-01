# Supprime la tâche planifiée « NQ Cockpit Alerter ».
$ErrorActionPreference = "Stop"

$taskName = "NQ Cockpit Alerter"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Output "Task '$taskName' removed."
