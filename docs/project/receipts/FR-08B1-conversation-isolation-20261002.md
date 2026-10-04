# FR-08B1 — conversation context isolation acceptance

Source parent: `ce2bf0d1920c0b7d181ea1da2dbbcbee357e0bcb`.
Scope: new acceptance tests only, no application/owner-policy/workflow changes.
Status: isolated local acceptance; no new protected GitHub CI or production deployment claimed. FR-08 as a whole remains open.

## Real database and explicit provider boundary
A dedicated PostgreSQL 16 container ran with `--network none`, no published ports, a private newly-created Unix-socket directory, 512 MiB memory cap, and tmpfs data. Container image: `sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685`. No production URI/configuration/database or real provider was used. Tests ran as actual UID65534 with this candidate's exact pinned backend development requirements in a new venv. SQL transactions/locks and asyncio were real; provider transport was explicitly modeled.

The 13 new cases passed, then the combined suite with `test_fr07_governed_conversations.py` passed **48/48**, zero failures/errors/skips. The 13 are included in 48, not additive. Combined JUnit SHA256: `5bdda356311ffcdd1d5e7f796122a66fdc13a50b1d9d970c30ee06977c1f23af`. All 1199 exported baseline backend/core input files matched after tests; the new test source was separately hashed. Existing deprecation warnings were retained, not treated as skipped tests.

## Exercised contracts
- One synthetic user, three projects, nine distinct conversations, two turns each: isolated sentinels in durable message history and the exact provider-context payload. All nine admitted dispatches overlapped at the modeled provider barrier after real database claims. This exercises direct concurrent `run_turn` calls, NOT fair automatic queue scheduling or production throughput.
- Private history/send/list boundaries for other users in both the same organization and another organization. Existing organization-scoped project collaboration policy was not changed.
- Identical request keys across users/conversations; duplicate concurrent requests reserve once per conversation, and competing dispatches execute only once. A creation key cannot silently move to another project.
- An uncertain turn blocks only its own conversation and is not automatically replayed; a sibling conversation can complete.
- Owner pause/resume retains the original age and history while a sibling remains usable.

## Retained failed setup and cleanup
The first new test module failed collection due to an incorrect sibling fixture import. The import was corrected to the existing `tests` package without changing application code or assertions; the initial failure is retained. A separate earlier scheduler probe had a launcher PATH error before any child started; it is not an application failure.

The new database container was identified by its exact ID and this run's label, stopped normally, removed, and absence verified. Synthetic database contents were disposable; all test code/results/manifests were retained. No existing container or host configuration was changed.

Evidence directory: `docs/project/runtime/fr06-recurring-task-health/interactive-unified-acceptance-20261002T180729518564Z-316b2936/`. Primary artifacts: `fr08b-combined-result.json`, `fr08b-combined.xml`, `fr08b-after-input-proof.json`, `fr08b-lab-cleanup-result.json`, `FR-08A-SOURCE-INVENTORY.json`, and the exact new test sources.

## Still open
Multi-tab browser tests, project artifact isolation, longer-history boundaries, sustained multi-worker fair scheduling/resource limits, real provider acceptance, 1000-user expanded capacity, protected source review and production acceptance are NOT closed by these cases. FR06 production encryption/migration, independent live executor adoption, and historical effects remain separate.
