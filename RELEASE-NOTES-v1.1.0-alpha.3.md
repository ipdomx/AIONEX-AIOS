# AIOS v1.1.0-alpha.3 — Reliability Foundation

This release adds the first durable reliability layer:

- Persistent error knowledge base with fingerprints, recurrence counts, root causes, prevention rules, and verified resolutions.
- Experiment gate requiring repeated successful evidence before an action is declared ready.
- Durable deduplicated memory with revision history.
- Project server connector registry with HTTP and TCP health checks and an extensible adapter boundary.
- Kernel integration and reliability status reporting.
- Database migrations that preserve existing project data.

## Safety
No secret is stored in connector profiles. This release does not autonomously deploy, modify production systems, or bypass human approvals.
