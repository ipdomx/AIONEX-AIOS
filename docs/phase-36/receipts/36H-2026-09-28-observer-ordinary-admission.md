# Phase36 36H — Observer ordinary-cycle admission

Date: 2026-09-28. Related source part: FR-06C5D11B.
Base main: PR777 merge a8c13247d1eacc9e52327c05f2084bcc65b12b91.

The operations observer now protects ordinary model-evidence refresh, probes,
retention and notification publication with independent schema8 admission.
The existing safety reconciliation transaction remains outside that fence and
commits first. Auto-disarm and uncertain-execution manual review are not frozen
or silently converted to settled execution. No schema version or scope changes.

The unchanged baseline reproduced8 failures among11 cases. Fixed acceptance
passed30 focused PostgreSQL cases and56 combined observer/model/growth cases.
Closure waits through admitted postcommit publication and owned thread effects;
real synthetic pilots are still durably disarmed while ordinary admission is
closed, or before unrelated ordinary failure. Counts overlap.

D10 and D11A already-deployed worker updates are not repeated. FR-07 remains
complete. These source/laboratory results do not prove deployment, provider drain
or encrypted host cutover. Blocked provider/bootstrap/postrelease actions were
not retried. See the canonical D11B project receipt and runtime evidence.
