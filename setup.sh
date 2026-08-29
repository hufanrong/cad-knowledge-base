#!/usr/bin/env bash
# ============================================================
#  CAD Knowledge Base - One-click setup (Linux / macOS)
#  Creates venv, installs CPU torch + requirements, copies .env
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/3] Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "[2/3] Upgrading pip and installing dependencies (first run ~3GB, please wait)..."
python -m pip install --upgrade pip
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt

echo "[3/3] Creating .env from template..."
if [ ! -f .env ]; then
    cp .env.example .env
fi

echo ""
echo "============================================================"
echo " Installation complete!"
echo " Activate environment : source venv/bin/activate"
echo " Check status        : python -m src.cli.main status"
echo " Launch GUI          : python -m src.cli.main gui"
echo " Launch REST API     : python -m src.cli.main serve"
echo " Edit .env for DB/ODA/LLM settings"
echo "============================================================"
