# FR08E native Owner, realtime and fresh synthetic recovery evidence

Verified on NEW `nc-ph-4354` only at 2026-10-11T19:16:49.822981+00:00. This receipt records **170/170 passing checks** against selected original routes with fresh synthetic fixtures. The canonical application acceptance remains in progress.

| Boundary | Verified result |
| --- | --- |
| Production application | Commit `f2527cf3815d21353916697e61a3409d2a9c62b3`; immutable Backend image `sha256:b718477e0b82c58920ee3d11baf2402d6cf54f920ecc763cd4a95106b5780b39` |
| Native package | Exact bytes of 482 git-tracked `src` files; read-only lab mount equivalent to the production Python path |
| Synthetic identities | Five accounts, two tenants; explicit project read/write permissions and native Super Owner role |
| Route execution | Real loopback HTTP and WebSocket; original native auth, projects, project conversations, Owner conversation governance and realtime lifecycle |
| Owner policy | Hierarchy, quotas, version conflict/concurrency, pause/resume, expiration and global/plan disable enforcement |
| Durable admission | One native queued job; retry retains the same ID and message charge; conflicting payload and second pending turn are guarded |
| Realtime | Tenant-scoped connections, ping/pong, disconnect cleanup, reconnect, auth-version revocation and new-session reconnect |
| Recovery | Actual `pg_dump -Fc`, isolated lab PG/Redis restart, database recreate + `pg_restore`, selected API restart and native re-login |
| Recovered continuity | Original six projects, six conversations, policy versions, reserved message usage and one queued job remain present |
| Refresh continuity | Rotated refresh token remains revoked after Redis restart and PostgreSQL restore |
| Isolation | Four lab containers, separate encrypted Docker/containerd data, no host ports or external network, read-only rootfs, dropped capabilities and bounded resources |
| Cleanup | Zero temporary lab containers; synthetic database, signing environment and backup dump removed |
| Production continuity | 36 running, 35 healthy, zero unhealthy/restarting; original container identities, application HEAD and MCP hotfix preserved |

The two local Ollama-type provider fixtures are admission-only records pointing to an unused loopback port. No provider service, credentials, network request, paid call or inference ran. The queued job was not dispatched. No production customer database, R2 snapshot, full application router, production environment or signing credential was used.

The fresh recovery backup was **977783 bytes**, SHA256 `19979b4cdfdd6097cfabd7143de9a8810fd4e66682f1f1e1ff2a764fdd73351e`; the dump was removed after actual restoration. Native route/recovery evidence is retained without fixture passwords, JWTs or a signing environment.

| Evidence artifact | SHA256 |
| --- | --- |
| `CONTINUATION-CHECKPOINT.json` | `e6d959cda12d7b2e6d3501240a3e30bb7460fcd6d705abc649caf35092e63428` |
| `FRESH-SYNTHETIC-HTTP-SUBGATE.json` | `a0ef8c01831b268c9dae0e0d8fd6714e5b8d671415862b4123688d048fbc8aea` |
| `LAB-ORCHESTRATION-RECEIPT.json` | `36d03e9797b61f9d70ba64df945fbdd37adb91274c0622a0a23dc75b77cc8418` |
| `NATIVE-SOURCE-PROJECTION.json` | `babe873dd2a484cb9aa8bdebcd9204ff82b857a5140eb811c570f90757a4668d` |
| `subgate_app.py` | `99208a5bf90415aabafe4e32b405177231e2a2e5312706a46e4dbd15b9d25017` |
| `subgate_check.py` | `ff5c9ad30a599a30dae0101df97e33527c7a3ffcae791594ffcfd354edc16b16` |
| `owner_realtime_extension.py` | `90c6d80a651920d0cc7404aa3600c3701aa3221f0d01e787c2f6c5b4cdf8d42d` |
| `fresh_recovery_extension.py` | `b7728f08945f723178039e595269f528535a3ddc34988b35c8c69e72034296fb` |
| `run_fresh_subgate.py` | `63e88bdae0fe9f6b6f3a617fa965bb96a27f38e5abe9954c7ed5236d59de3870` |

Native artifact directory: `/var/lib/aionex-migration/r1-management-20261008/FR08E-OWNER-REALTIME-FRESH-RECOVERY-20261011`. Two source-import setup attempts and the accepted 143-check checkpoint remain archived; the final 170-check run completed with harness exit code zero. Corrective work was confined to the isolated harness/import projection. Product application source was not changed.

Canonical event: `fr08e-owner-realtime-fresh-recovery-subgate-20261011T191649Z`, `FR-08=in_progress`, `verification_passed=false` for the full gate, with the four selected subgate flags true. Worker/inference/media execution, independent full customer R2 recovery, FR06/NS14A and actual sustained 5000-user load remain to be accepted.

The existing canonical FR09 profile/evidence tests on protected main `493cbc35cfa60c08b0e77893e8d852d39182efac` passed **41/41** with their source unchanged. Canonical PLAN and the original seven-stage ramp already enforce 5000 active users, three projects and conversations per user, 15000 durable jobs and 15-minute steady state, read P95 <=500 ms, enqueue P95 <=1000 ms, error rate <=0.005 and zero tenant leaks/lost jobs/duplicate terminal execution. The five original main workflows and eleven check runs were all successful. PR [#899](https://github.com/ipdomx/AIONEX-AIOS/pull/899) was closed as superseded; it was not merged and its obsolete test/source were not edited. Source proof: `/var/lib/aionex-migration/r1-management-20261008/CANONICAL-FR09-SOURCE-RECONCILIATION-20261011.json`.

Live tracker: [#884](https://github.com/ipdomx/AIONEX-AIOS/issues/884). This receipt does not close the retirement or release acceptance gates.
