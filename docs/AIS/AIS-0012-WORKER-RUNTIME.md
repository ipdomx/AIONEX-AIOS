# AIS-0012 — Worker Runtime and Evidence-Based Delivery

## Purpose
Phase 3 introduces a digital-worker runtime that connects career records, academy status, operational health, task assignment, evidence submission, review, rework, and performance history.

## Mandatory rules
1. Suspended, retraining, or retired workers cannot receive assignments.
2. Required skills must be present before assignment.
3. Completion requires evidence for every acceptance criterion.
4. Failed review creates rework and is recorded in the career history.
5. Successful review records success and immutable performance evidence.
6. Worker runtime communicates through its public API and does not mutate ministry internals.
