#!/usr/bin/env bash
set -euo pipefail

python -m compileall app main.py
python - <<'PY'
from main import app

paths = set()
for route in app.routes:
    effective_route_contexts = getattr(route, "effective_route_contexts", None)
    if callable(effective_route_contexts):
        paths.update(
            context.path
            for context in effective_route_contexts()
            if getattr(context, "path", None)
        )
    elif getattr(route, "path", None):
        paths.add(route.path)

required = {
    "/health",
    "/ready",
    "/api/v1/auth/login",
    "/api/v1/auth/firebase/phone/public",
    "/api/v1/projects",
    "/api/v1/integration/health",
}
missing = sorted(required - paths)
if missing:
    raise SystemExit(f"Missing required routes: {missing}")
print("Backend verification passed")
PY
