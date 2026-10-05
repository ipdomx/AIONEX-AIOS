# FR-13A — Independent identity-media operation acceptance preparation

This receipt records bounded FR-13-owned source acceptance evidence for PR #852.
FR-12 is merged on protected main, but FR-13 remains operation-specific: no row is
bulk-promoted and this receipt does not claim live-provider acceptance, production
deployment, or final FR-13 closure.

## Seven-operation matrix

The companion fixture contains exactly seven explicit rows and is checked against
the current protected-main access/runtime/provider maps:

1. voice_clone — runtime ready; provider canary evidence exists.
2. voice_transform — runtime ready on the current source and mapped to
   `adirik/hierspeechpp`; no distinct FR-13 provider canary is asserted here.
3. face_reenactment — runtime ready with the current provider model mapping,
   but no distinct per-operation provider canary located by FR-13 so far.
4. face_swap — FR-12 is merged, but the current identity-media runtime-ready set
   and API/provider model maps still do not expose face_swap; it therefore remains
   runtime pending and independently unaccepted.
5. talking_head — runtime ready with the current provider model mapping, but
   no distinct per-operation provider canary located by FR-13 so far.
6. lip_sync — runtime ready; provider canary evidence exists.
7. avatar_generation — runtime ready; provider canary evidence exists.

The test binds those rows to the current source operation list, runtime-ready set,
API/provider model maps, rights/Owner/revocation controls, synthetic-media
disclosure requirement, and cost truth. Its static AST reader resolves only
top-level scalar literal names referenced by literal containers; it does not
import or execute runtime/provider code.

## Rights, Owner approval, revocation, and disclosure

The acceptance contract preserves the existing requirements for rights evidence,
Owner approval where required, revocation checks before provider submission and
delivery/download, and mandatory synthetic-media disclosure. A shared control is
not treated as proof that every operation has identical provider/runtime evidence.

## Cost truth

`max_cost_authorization_usd` is an authorization ceiling, not an invoice.
`actual_cost_usd` remains null/unknown unless a provider reports an actual cost.
The test explicitly rejects treating the ceiling as billed/actual cost.

## Dependency boundary

FR-12 is merged on protected main. That satisfies FR-13's declared dependency,
but it does not make face_swap runtime-ready by itself and it does not authorize
bulk promotion of any operation. Final FR-13 acceptance still follows the
operation-specific source/runtime evidence represented by the seven rows.

No live provider call, paid request, customer-data access, database/service/key
mutation, production deployment, Cloudflare change, or runtime mutation is part
of this source repair.

## Repair validation

- Targeted FR-13 failing test with conftest disabled: PASS.
- Full FR-13 static acceptance file with conftest disabled: 4/4 PASS.
- Normal backend pytest collection on this host remains unavailable because the
  host Python environment lacks SQLAlchemy; no package installation was attempted.
- Python compilation of the modified FR-13 test: PASS.
- Modified fixture JSON parse: PASS.
- Phase 36 reporting invariant against the three changed FR-13 paths: PASS.
- `git diff --check`: PASS.

These checks validate the deterministic FR-13-owned repair only. Protected CI on
the exact pushed PR head remains the authority for repository-wide integration.
