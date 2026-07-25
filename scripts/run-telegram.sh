#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
set -a
[ -f .env ] && source .env
set +a
aios-telegram
