#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_*.py'
