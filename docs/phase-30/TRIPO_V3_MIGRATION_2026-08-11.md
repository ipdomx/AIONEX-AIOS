# Tripo V3 migration — 2026-08-11

## Scope

The autonomous full-3D project path no longer uses the retiring Tripo V2 OpenAPI surface.
The server-side adapter is V3-only and keeps the API key on the backend/project-worker.
There is no V2 fallback.

## Production contract

- Base URL: `https://openapi.tripo3d.ai/v3`
- Text-to-model: `POST /generation/text-to-model`
- Task polling: `GET /tasks/{task_id}`
- Wallet preflight: `GET /account/balance`
- Model: `P1-20260311` for bounded low-poly web assets.
- Generation request uses V3 `model`, `prompt`, `model_seed`, `face_limit`, `texture`, and `pbr` fields.
- Successful task output is read from `output.model_url`.
- Actual usage evidence is read from `credits_consumed`.

## Safety and billing behavior

- Wallet balance is checked before autonomous provider generation.
- `PROJECT_3D_TRIPO_CREDITS_PER_ASSET` is a conservative planning floor only; it is not treated as provider pricing truth.
- The provider-reported `credits_consumed` value is retained in execution evidence.
- Insufficient credit or provider unavailability degrades to verified project assets/procedural zones instead of producing fake success or crashing the full project delivery.
- Download URLs remain SSRF-guarded, HTTPS-only, redirect-bounded, size-bounded, and GLB-magic validated.

## Acceptance gates

Before merge, the migration must pass:

1. V3 request/poll/balance contract tests with no V2 route in executable code.
2. Root regression suite.
3. Full isolated PostgreSQL/Redis backend suite and migrations.
4. Ruff and mypy.
5. GitHub protected CI, CodeQL, SBOM/dependency and Production Docker gates.
6. Production backup before deployment.
7. V3 wallet preflight and one bounded live text-to-3D task after deployment.
8. GLB integrity/inspection and complete `3d_full` web assembly with browser/performance/release gates.
