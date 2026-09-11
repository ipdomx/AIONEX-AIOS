# 36N — FR-03 Python compatible dependency split

The current Dependabot Python runtime group was reviewed against the live dependency graph. `uvicorn[standard]==0.52.4` conflicts with the retained `websockets==12.0` pin because Uvicorn now requires WebSockets >=13. That cross-boundary migration remains isolated to FR-03C. This receipt covers only the compatible minor/patch/dev-tool updates plus Selenium 4.48.0 with its existing project-worker contract adjusted accordingly.

Local acceptance: dependency resolution PASS for runtime and full backend manifests; Core `956/956` PASS; project-worker contract `6/6` PASS; runtime `pip-audit` reports no known vulnerabilities. No deployment is performed in this receipt.
