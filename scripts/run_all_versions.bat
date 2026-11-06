@echo off
REM Launch every archived version, each in its own minimised window and port.
REM v00 -> 8510, v01 -> 8511, and so on. Port 8501 is never used.
setlocal
cd /d "%~dp0.."
echo Starting all NQ Cockpit versions (one minimised window each)...
for /f "usebackq delims=" %%t in (`git tag --list "v*" --sort=version:refname`) do (
    echo   %%t
    start "NQ %%t" /MIN powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_version.ps1" -Tag %%t -NoBrowser
)
echo.
echo Each version listens on 8510 + its number (v00 = 8510 ...).
echo The current app on 8501 is not touched.
echo Stop them all with: scripts\stop_versions.bat
