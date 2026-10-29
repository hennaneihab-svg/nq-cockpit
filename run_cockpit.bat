@echo off
cd /d "%~dp0"
start "NQ Cockpit" /MIN ".venv\Scripts\python.exe" -m streamlit run "src\nqcockpit\ui\app.py" --server.headless true --server.port 8501
ping -n 6 127.0.0.1 >nul
start "" "http://localhost:8501"
