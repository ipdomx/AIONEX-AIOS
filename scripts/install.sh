#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
cp -n .env.example .env || true
mkdir -p data logs backups workspaces
python -m unittest discover -s tests -p 'test_*.py'
echo "AIOS Enterprise installed successfully."
echo "Run: source .venv/bin/activate && aios init"
