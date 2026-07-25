# AIONEX AIOS v2.2.0-beta.3 — Phase 1

## Government & Workforce Health Foundation

This additive phase introduces two isolated modules:

- `src/aios/government/`
  - constitutional court
  - executive, wisdom, future, research, and crisis councils
  - owner-only final approval office
  - evidence-based governance runtime

- `src/aios/workforce_health/`
  - digital-worker operational health monitoring
  - performance, collaboration, learning, and policy-compliance scoring
  - dedicated advisor assignment
  - retraining, supervision, restriction, promotion, and recertification recommendations

The workforce-health module evaluates digital agents only and does not make human medical diagnoses.

## Safety properties

- Missing evidence returns proposals for revision.
- External analysis requires authorization.
- Irreversible actions require a rollback plan.
- Owner approvals cannot be issued by another role.
- Low-reliability workers receive explicit restrictions rather than silent acceptance.
