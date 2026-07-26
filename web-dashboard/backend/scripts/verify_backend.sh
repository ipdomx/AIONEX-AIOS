#!/usr/bin/env bash
set -euo pipefail

python -m compileall app main.py
python - <<'PY'
from main import app

paths = {route.path for route in app.routes}
required = {
    "/health",
    "/ready",
    "/api/v1/auth/login",
    "/api/v1/projects",
    "/api/v1/integration/health",
}
missing = sorted(required - paths)
if missing:
    raise SystemExit(f"Missing required routes: {missing}")
print("Backend verification passed")
PY
