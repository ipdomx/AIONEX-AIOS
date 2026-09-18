# FR-06C5D7C — align the roadmap with merged source, not deployment

Reviewed source: `647b2e15f59999925f916b0eb372e9a2236d8678` (PR #722).
Registry source: `0e26a756b1a0486ebf8de312d3fa51678d226f7b` (PR #720).

## Observed documentation defect

The current PLAN still selected D7B2 and migration 0052, and listed creation of
the durable scan registry and runtime wiring as unimplemented work. Both are
present in merged source. This could cause a later session to repeat accepted
implementation instead of reviewing the actual operational prerequisites.

## Bounded correction

The parent source pointer now selects D7B8 and migration 0053. A current runtime
contract records the registry and worker composition already merged in #720 and
#722. D7A, D7B1 and D7B2 remain preserved as historical part-specific contracts,
with explicit references to the current runtime contract; their historical
limited-scope statements are not rewritten as production claims.

The current runtime contract deliberately keeps production deployment, production
database migration, production ZAP exclusivity, automatic settlement of old work,
full-host closure, and full D7 completion false. Database fencing applies to
cooperating callers; it is not a claim that every production ZAP client is fenced.
Cancellation remains intent, ambiguous work retains its fence, and the synthetic
real-daemon lab does not certify all scanner rules or production containment.

Post-merge checks and canonical source synchronization remain live-journal facts,
not immutable success values inside the tracked PLAN. The remaining work now
separates source acceptance, production containment and legacy reconciliation,
other worker/producer/realtime coverage, measured drain, and the later protected
backup/restore/maintenance cutover.

## Validation boundary

`tests/test_fr06c5d7_source_runtime_boundary.py` checks the current source pointer,
actual implementation and migration paths, preserved historical contracts,
unresolved-work semantics, dynamic acceptance provenance, and non-closure of
production and parent scope. These are documentation/source contract tests, not
new execution, load, scanner or production acceptance tests. Exact test outcomes
and protected-merge status belong in the canonical runtime receipt.

No application code, container definition, production database, production data,
Cloudflare setting or vault state is changed by this documentation correction.
