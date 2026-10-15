@echo off
setlocal
cd /d "%~dp0"
title NQ Cockpit - Lancement

echo ========================================================
echo        NQ COCKPIT -- Lancement Automatique
echo ========================================================
echo.

if not exist .venv (
    echo [1/3] Creation de l'environnement virtuel Python (.venv)...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer l'environnement virtuel. Verifiez que Python 3.11+ est installe.
        pause
        exit /b 1
    )
    echo [2/3] Installation des dependances (MetaTrader5, Streamlit, etc.)...
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    pip install -e .
) else (
    call .venv\Scripts\activate.bat
)

if not exist .env (
    echo [INFO] Creation du fichier .env par defaut...
    copy .env.example .env >nul
)

if not exist config.yaml (
    echo [INFO] Creation du fichier config.yaml par defaut...
    copy config.example.yaml config.yaml >nul
)

echo [3/3] Demarrage du cockpit NQ...
echo L'application demarre sur http://localhost:8501.
echo.
python -m nqcockpit run
pause
