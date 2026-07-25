# ADR-0006: Reliability Memory and Experiment Gates

## Status
Accepted for AIOS v1.1.0-alpha.3.

## Decision
AIOS shall persist operational errors, prevention rules, successful resolutions, experiment evidence, server connector profiles, and memory revisions. An action is not considered proven merely because it succeeded once. High-impact execution must pass a configurable repeatability gate in an isolated workspace before approval or deployment.

## Principles
1. Failures become reusable knowledge, not disposable logs.
2. Repeated identical errors increase one incident record instead of creating noise.
3. Memories are deduplicated, revision-audited, and may be re-verified after correction.
4. Credentials never enter connector profiles or release archives; profiles refer to environment-managed secrets.
5. Connectors are adapter-based so future protocols can be added without changing the cognitive core.
6. AIOS never promises infallibility. It reduces recurrence through evidence, controls, rollback, and human approval.
