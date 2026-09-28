$ErrorActionPreference = "Stop"
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
New-Item -ItemType Directory -Force -Path vendor | Out-Null
Set-Location vendor
if (!(Test-Path gex-dashboard)) { git clone https://github.com/Darthreign/gex-dashboard.git }
if (!(Test-Path gammagrid))     { git clone https://github.com/gammagrid/gammagrid.git }
if (!(Test-Path gex-analytics)) { git clone https://github.com/pikki622/gex-analytics.git }
Set-Location ..
if (!(Test-Path .env)) { Copy-Item .env.example .env }
if (!(Test-Path config.yaml)) { Copy-Item config.example.yaml config.yaml }
Write-Host "Installation terminee. Etape suivante : ouvre le dossier dans Antigravity et lance prompts/P00."
