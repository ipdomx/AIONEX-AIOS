# FR-17B — Academy learner readiness and privacy boundary

Observed UTC: 2026-10-03T00:46:42.931272+00:00
Source base: 1466516d4ce4d78290f34050ba832036c85c2655

## Scope

This FR-17-owned source step narrows the learner-facing package-readiness contract. It does not modify the shared Academy API endpoint, deploy production, use live learner data, or claim educational/medical accreditation.

## Change

academy_course_runtime.package_snapshot() now reports package download/site readiness only for approved packages. A review_pending package remains reviewable but is not represented as learner-ready.

The snapshot continues to omit raw archive/site storage paths. Existing teacher answer-key and endpoint authorization remain separate contracts; the FR-25 cross-scope request for the shared endpoint remains required because that endpoint currently has its own direct status checks.

## Targeted acceptance

The dedicated FR-17B tests cover:
- review_pending => download/site not learner-ready;
- approved => learner-ready;
- rejected => not learner-ready;
- learner snapshot does not expose raw archive/site storage paths.

This is synthetic source acceptance only. FR-08 still gates integration/live/final FR-17 closure. Human review remains required for sensitive professional/healthcare use and this receipt makes no clinical-validation claim.


## Test evidence

Observed after source edit at 2026-10-03T00:48:00.961931+00:00.

- Initial normal backend pytest collection could not start because the host test interpreter does not have SQLAlchemy installed; no test body ran.
- The dedicated FR-17B contract test was made dependency-independent and executed with pytest --noconftest against the exact edited source contract.
- Result: 3 passed in 0.02s.
- No live services, database, provider, customer data, or production state were touched.

The shared web-dashboard/backend/app/api/v1/endpoints/academy.py still has direct review_pending-or-approved download/site checks outside FR-17 ownership. The existing FR-25 serialized patch request remains required before learner-facing pre-approval access is closed end-to-end.
