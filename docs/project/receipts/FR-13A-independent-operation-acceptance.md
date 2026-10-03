# FR-13A — Independent identity-media operation acceptance preparation

This receipt records bounded FR-13-owned source preparation only. It does not
claim FR-13 integration, live acceptance, or final closure while FR-12 remains
unaccepted.

## Seven-operation matrix

The companion fixture contains exactly seven explicit rows:

1. voice_clone — runtime ready; provider canary evidence exists.
2. voice_transform — runtime pending; no bulk promotion.
3. face_reenactment — runtime ready with the current provider model mapping,
   but no distinct per-operation provider canary located by FR-13 so far.
4. face_swap — runtime pending and explicitly gated by FR-12.
5. talking_head — runtime ready with the current provider model mapping, but
   no distinct per-operation provider canary located by FR-13 so far.
6. lip_sync — runtime ready; provider canary evidence exists.
7. avatar_generation — runtime ready; provider canary evidence exists.

The test binds those rows to the current source operation list, runtime-ready
set, API/provider model maps, rights/Owner/revocation controls, synthetic-media
disclosure requirement, and cost truth.

## Cost truth

max_cost_authorization_usd is an authorization ceiling, not an invoice.
actual_cost_usd remains null/unknown unless a provider reports an actual
cost. The test explicitly rejects treating the ceiling as billed/actual cost.

## Dependency boundary

FR-12 is still unaccepted. Therefore this FR-13A package intentionally leaves
voice_transform and face_swap unpromoted where the current source says runtime
acceptance is pending, and it makes no claim that FR-13 is integrated, live, or
complete.

No provider, paid, customer-data, database, service, key, or production effect
is part of this preparation.

## Isolated validation

- Python compilation of the FR-13 test: PASS.
- Fixture JSON parsing: PASS.
- Normal backend pytest collection was unavailable on this host because the
  host Python environment does not contain SQLAlchemy; no package installation
  was attempted.
- The FR-13 test is intentionally standard-library/static-source only and was
  run with pytest conftest loading disabled: 4/4 PASS.
- git diff --check: PASS.

These results validate only the isolated FR-13A acceptance contract against the
current source snapshot. They do not satisfy the FR-12 dependency or authorize
integration/live/final closure.
