@echo off
REM Run one archived version of NQ Cockpit on its own port.
REM   scripts\run_version.bat v03-symbols
REM   scripts\run_version.bat            (lists versions)
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_version.ps1" %*
if "%~1"=="" pause
