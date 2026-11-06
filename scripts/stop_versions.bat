@echo off
REM Stop ONLY the version servers listening on ports 8510-8529.
REM The main application on port 8501 is never touched.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -ge 8510 -and $_.LocalPort -le 8529 }; if (-not $c) { Write-Host 'No version server is running on ports 8510-8529.'; exit 0 }; $pids = $c | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($procId in $pids) { $p = Get-Process -Id $procId -ErrorAction SilentlyContinue; if ($p) { Write-Host ('Stopping ' + $p.ProcessName + ' (PID ' + $procId + ')'); Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } }; Write-Host 'Version servers stopped. Port 8501 was not touched.'"
