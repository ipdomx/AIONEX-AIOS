# FR-06 — current-main source consolidation (2026-10-01)

This successor integrates the exact original heads of PRs #830, #831, #833 and #834 onto protected main `7779f740a81d4fae2167c8441218b69e54cf56f5`, without rewriting their history or changing their source bytes/file modes. All nine inherited changed paths were compared by Git tree entry (mode and blob); no mismatch occurred. The two operational scripts retain mode 100755.

The goal is to resolve the repeated BEHIND dependency without bypassing strict branch-up-to-date protection. All required checks must run on this new combined head. Previous PR checks or local tests do not authorize its merge. No branch-protection rule, workflow, test expectation or security threshold is weakened.

Local integrated verification: 126 directed tests passed, with zero failures, errors or skips, across C5E12 runtime binding, activation authority, memory transaction, C5D12 service resume, C5D13 authority transitions and C5D14 backup/restore refresh. These tests use synthetic authority/kernel/provider boundaries as defined in their fixtures; they are not production execution evidence. The XML, log and exact tree-entry provenance are retained under `docs/project/runtime/fr06-recurring-task-health/interactive-resume-20261001T112633683536Z/`.

The older C5E9 maintenance progress receipt is historical evidence at its stated observation time, not a new assertion of current admission, service state, source SHA, or host closure. Every production use must revalidate current raw evidence, source, boot identity, maintenance operation/generation and exact accepted prerequisites.

No production action, service resume, admission transition, provider lookup, database settlement, memory activation, reboot or recovery is performed by this source consolidation. C5D15 remains separate unfinished source. Complete host-state migration, production/boot integration, writer freeze and encrypted swap plus /tmp acceptance, and C6 reboot/recovery still require their own evidence. FR-06 remains open; FR-07 remains complete.
