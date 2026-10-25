# FR09 authenticated project-list performance - bounded-page SQL and index

Source baseline: protected main c2f66b6; deployment: **not performed**.

The proposed query limits tenant project IDs in a PostgreSQL MATERIALIZED CTE
after the same live filters/order/offset/limit. Details, workspace/owner
joins and the per-project active-task count are evaluated only after paging.
Migration 20261025_0065 builds index ix_projects_org_created_at_desc
on (organization_id, created_at DESC) CONCURRENTLY, without writing project rows.

Validation: isolated PostgreSQL 16 upgrade to revision 0065 succeeded,
and 75 SQL/security/integration tests passed. Ruff checks were clean.

## 500 synthetic authenticated-user, 1500-project, 1500-task, 1500-inbox ABBA

6000 HTTP 200 responses over 4 phases, same 16 API shard profile and same
tenant/project/owner data. Comparison is the **combined** materialized query
and PostgreSQL index, not a claim that either change alone caused the delta.

| Route (P95 ms) | Old A1 | New B1 | New B2 | Old A2 |
|---|---:|---:|---:|---:|
| identity | 546.68 | 476.32 | 495.40 | 432.09 |
| projects | 606.53 | 476.49 | 398.53 | 704.64 |
| conversations | 369.05 | 379.35 | 306.64 | 305.65 |

New project P95 average: 437.51ms vs old 655.59ms.
Within this preserved R2 ABBA receipt, all 3 read routes stayed at or
below 500ms in both candidate phases. Earlier independent samples were
variable, so **steady target and 5000-user acceptance remain unproven**.

## 1000 synthetic authenticated-user ramp, 3000 projects/conversations/tasks

The 1000-user stage completed 3000 authenticated HTTP 200 but failed:
- identity: P95 669.81 ms
- projects: P95 724.05 ms
- conversations: P95 889.13 ms

Evidence accounting caveat: original harness metadata field
identical_synthetic_auth_bearers was hardcoded at 250, even in the
500/1000-user runs; it is NOT used as proof of unique bearer count.
The per-stage HTTP assertions and synthetic cohort seeding verified each
required cohort size. Preserve this discrepancy for harness hardening.

No 5000 authenticated active multi-tenant 15-minute mixed-load acceptance,
no 15000 genuine model inferences, and no 72 natural hours have been proved.
This is a guarded source candidate. **Final-release decision: HOLD.**
