# FR-12A — Face Swap provider contract

Status: **source contract prepared; live/runtime acceptance remains gated**

This batch adds a provider-neutral Face Swap admission contract and a bounded
Replicate transport for the pinned codeplugtech/face-swap version. The contract
requires two private execution-scoped image inputs, SHA-256 evidence, explicit
identity/rights basis, Owner approval for real-person identities,
synthetic-media disclosure acknowledgement, a bounded authorized cost ceiling,
and a stable idempotency key.

The transport accepts only HTTPS provider-input URLs using the existing signed
identity-media pull path, sends one creation request to the pinned Replicate
prediction endpoint, and treats timeout/transport/5xx submission outcomes as
ambiguous. Ambiguous creation is **never automatically replayed**. Prediction
polling is retryable where safe; output download is restricted to the existing
trusted Replicate delivery-host policy and the final image envelope is validated
before private persistence.

FACE_SWAP_RUNTIME_APPROVED remains False. This source batch does not wire Face
Swap into the shared live Identity Media worker, does not enable a provider,
does not grant rights/consent, and does not perform paid or real provider calls.
FR-11/provider-account/licensing/real-output gates remain prerequisites for
later live acceptance.

Owned files:
- web-dashboard/backend/app/services/face_swap_contract.py
- web-dashboard/backend/app/services/face_swap_adapter.py
- web-dashboard/backend/tests/test_fr12_face_swap_contract.py
- this receipt

Verification for this source batch uses only local/static execution and
httpx.MockTransport; no credentials or customer data are required.
