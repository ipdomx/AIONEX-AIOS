#!/usr/bin/env sh
set -eu

python -m pytest -q
python -m ruff check app tests
python -m mypy app

printf '%s\n' 'Backend quality gate passed.'
