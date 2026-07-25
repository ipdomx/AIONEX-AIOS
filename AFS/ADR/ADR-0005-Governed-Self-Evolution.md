# ADR-0005 — Governed Self-Evolution

## Status
Accepted.

## Context
AIOS must improve itself without becoming an uncontrolled autonomous updater.

## Decision
Permit AIOS to observe, diagnose, propose, and implement candidate changes only in isolated workspaces. Promotion requires policy checks, tests, review, approval, monitored rollout, and rollback support.

## Consequences
- AIOS can improve continuously while preserving human authority.
- Every self-change produces durable evidence and audit records.
- Direct self-modification of production is prohibited.
