# FR-06C5D7B9 — Production ZAP exclusivity

Source-only hardening after the coordinated FR-06 production rollout to Alembic 0062. Production evidence showed the ZAP daemon had no host port exposure and SecurityScanWorker executes scans inside a bound ScanResourceRuntime, but the shared `.env.production` caused ZAP URL/API-key variables to be inherited by unrelated database clients, while `run_zap()` retained a non-owned direct ZapClient fallback. Therefore production exclusivity could not truthfully be claimed.

B9 changes two boundaries only. First, `run_zap()` now fails closed in `ENVIRONMENT=production` whenever no durable scan runtime is bound; non-production direct adapter tests remain possible. Second, a dedicated additive `docker-compose.fr06-zap-exclusivity.yml` overlay explicitly overwrites `SECURITY_ZAP_URL` and `SECURITY_ZAP_API_KEY` with empty strings for every database client except `security-scan-worker`. The ZAP daemon remains network-internal, API-key protected, and without host port bindings.

This stage does not run a real scan, change ZAP state, migrate the database, settle legacy/ambiguous scan executions, or claim host drain/full-host closure. `production_zap_exclusivity_verified=false` until protected merge plus a selective Production rollout recreates affected clients and proves live environment isolation and production fail-closed behavior.

Final local source acceptance before PR: 3/3 B9 source-contract tests passed; 5/5 focused backend ZAP tests passed; the complete root repository suite passed 1965/1965. Ruff passed the changed service/test, Mypy reported no issues in `security_zap.py`, and Phase 36 reporting, PLAN JSON, py_compile and git diff checks passed.

A full Production Compose render using the live `.env.production`, all currently active FR-06 overlays, plus the new B9 overlay showed non-empty ZAP-related variables only on `security-scan-worker` (`SECURITY_ZAP_URL`, `SECURITY_ZAP_API_KEY`) and `security-zap` (`SECURITY_ZAP_API_KEY`); neither service exposes host ports. Source audit found the only application `ZapClient()` construction in `security_zap.py`, after the new Production ownership guard. Test/lab-only direct clients remain outside Production runtime.

No real scan, ZAP daemon mutation, Production container recreation, or credential change was performed by this source acceptance.
