# Phase 18 — Self-Evolution & Research Engine

Batches 1 through 6 implement:

- Improvement proposal domain and lifecycle
- Evidence-first research questions and confidence scoring
- Guarded experiments with control, candidate, observations, and rollback version
- Promotion gate requiring owner scope, approved proposals, successful experiments, and observations
- Unit tests for evidence, ownership, experiment lifecycle, and promotion decisions

## Validation criteria

1. CodeQL passes.
2. Final Validation passes.
3. Cross-owner access is rejected.
4. Proposals cannot be approved without verified evidence.
5. Experiments cannot be promoted unless they succeed and record observations.
6. Every experiment retains an explicit rollback version.
