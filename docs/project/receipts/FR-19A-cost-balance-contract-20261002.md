# FR-19A — cost/balance provenance contract

Date: 2026-10-02
Source base: 1466516d4ce4d78290f34050ba832036c85c2655
Run: fr19-scheduled-20261002T215441Z-6ac002d8

## Scope

This receipt covers only the FR-19A source contract and targeted tests. It does
not claim FR-19 integration, live delivery acceptance, provider billing API
availability, actual provider invoice reconciliation, or final closure.

## Verified source semantics

- Measured provider spend is the durable sum of
  ProjectAIRouteAttemptRecord.actual_microusd plus the provider runtime's
  recorded runtime_spend_microusd.
- estimated_microusd is not used as measured spend by
  provider_total_spend_microusd; estimates and measured spend remain distinct.
- Numeric funding is an Owner-recorded funded baseline minus recorded measured
  spend. It is not represented as a provider invoice or provider-reported bank
  balance.
- numeric_private permits threshold monitoring while redacting funded,
  remaining and threshold amounts from general/public notification payloads.
- owner_attested confirms funding without inventing a numeric balance. Numeric
  funded/remaining/threshold values stay unavailable and the state is
  funded_attested; billing/quota failures remain alertable.
- Explicit billing failure alerts do not depend on a numeric balance and their
  payload contains provider identity/type and failure code only.

## Test boundary

The FR-19A tests are synthetic, DB-free and provider-free. They make no network
calls, read no credentials, make no paid requests, and do not validate live
notification delivery. They verify classification, source-query provenance,
redaction, predictive-gap behavior and billing-failure payload boundaries.

## Remaining before FR-19 closure

1. Integrate only through the FR-25 coordinator after protected review.
2. FR-08 must be accepted before FR-19 dependent integration/live acceptance.
3. Prove Owner alert delivery at a controlled test threshold and on an explicit
   billing/quota failure without exposing secrets.
4. Publish provider/source-specific accuracy evidence that distinguishes
   measured spend, estimates/caps, Owner-entered funding and any genuinely
   supported provider-reported balance source.
5. Do not treat spending caps or Owner attestations as actual provider bills.
