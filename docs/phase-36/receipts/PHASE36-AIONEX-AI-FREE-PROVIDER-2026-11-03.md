# Phase 36 Reporting Receipt — AIONEX AI as the free project-AI model

- Receipt ID: PHASE36-AIONEX-AI-FREE-PROVIDER-2026-11-03
- Batch: 36C (launch model policy) — follow-up
- Date/time UTC: 2026-11-03
- Objective: Route free-tier project AI to the owner's own model (`ollama:aionex-ai`), retire the weak local models `qwen2.5:1.5b` / `gemma3:4b`, and show clear bilingual limit/upgrade messages.
- Production gap before change: free project AI depended on a 1.5B local model with poor quality; limit errors exposed raw codes without reset time or upgrade guidance.
- Changed paths/services/schemas: `project_ai_launch_models.py`, `project_ai_access_policy.py` (free default), `conversation_governance.py`, `free_tier.py`, compose `ollama-model-bootstrap` (no model pull), project-worker `selenium==4.52.0`, frontend lockfile `follow-redirects@1.16.2`, FR-06B2 render proof hash, related contract tests (including `tests/test_phase36_autonomous_3d_full_project.py` selenium pin). No schema change.
- Technology/version review and official sources: selenium 4.52.0 (PyPI) bundles selenium-manager with Rust `zip` 9.0.5, fixing CVE-2026-115905/-115907/-115908; follow-redirects 1.16.2 (npm) fixes GHSA-mrwp-f3q8-3g9p.
- Security/privacy/cost/sector review: free tier stays local-only and zero external spend (`offline_only`, `max_project_cost_usd=0`); AIONEX AI endpoint is private to the AIOS Docker network (CIDR-restricted). No secrets in source.
- Tests and exact pass counts: CI Backend Tests 2985 passed / 1 failed (fixed in this change: default free policy assertion); ruff clean; `mypy --no-incremental app` no issues (317 files); compose/runtime contract tests pass; FR-06B2 validator PASS for both env profiles.
- Performance/load evidence: live synthetic free project on the real invoker path — planner 14.7 s, compact-spec coder 29.6 s (valid JSON), $0; chat ~3 s on CPU fallback.
- Problems discovered: overlay files copied as root 0600 were unreadable by the app user (first rollout auto-rolled back); render proof hash drift after compose edit; two new upstream advisories.
- Root causes and why prior safeguards missed them: overlay build did not preserve original ownership; the render proof pins the compose hash by design; advisories were published after main's last green run.
- Fixes and regression tests: `COPY --chown=1000:1000`; validator re-run and proof updated; dependency bumps; tests updated.
- PR / merge SHA / protected checks: PR #1018 (this branch).
- Backup / deployment / rollback: deployed via guarded rollout (overlay images `:aionexai-free-9bfa363-20261103`, PASS, 32 healthy, unrelated containers unchanged); rollback override retained on the host; DB backups recorded before policy changes.
- Live acceptance and before/after metrics: launch evidence refresh validates `ollama:aionex-ai`, nothing unavailable; daily missing-model warnings stopped.
- External activation gates remaining: none for the free tier; paid plans remain inactive with bounded default limits set by the owner panel.
- Next action: owner merge of PR #1018.
