#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
mkdir -p vendor && cd vendor
[ -d gex-dashboard ] || git clone https://github.com/Darthreign/gex-dashboard.git
[ -d gammagrid ]     || git clone https://github.com/gammagrid/gammagrid.git
[ -d gex-analytics ] || git clone https://github.com/pikki622/gex-analytics.git
cd ..
[ -f .env ] || cp .env.example .env
[ -f config.yaml ] || cp config.example.yaml config.yaml
echo "Installation terminée. Ouvre le dossier dans Antigravity et lance prompts/P00."
