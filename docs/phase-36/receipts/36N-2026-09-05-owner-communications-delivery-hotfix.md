# Phase 36N — Owner Communications Delivery Hotfix

- Date: 2026-09-05 UTC
- Scope: post-launch owner alert delivery hardening after PR #551 activation.
- Base: merged `main` commit `2d39a3c98068df72cd5a8a0c2f11a744dd3fe1e7`.

## Detection

The live provider-credit cycle persisted three predictive-monitoring notifications for the funded-attested OpenAI, DeepSeek, and Mistral providers. In-app delivery was `delivered`, proving the durable notification path. External delivery exposed two independent configuration/runtime defects that must not be hidden behind a successful in-app result:

1. SMTP delivery returned `SMTPSenderRefused`. Production has a dedicated `SMTP_FROM_EMAIL`, but both the durable communications sender and the Owner SMTP test path used the SMTP login username as the RFC-5322 `From` address.
2. Owner Telegram selection returned unconfigured even though the protected Owner token exists and the allowlist contains exactly one Owner identity. The token bind source is root-owned mode `0600`, while application processes run as UID/GID `1000:1000`. In addition, `operations-observer` did not receive the Owner Telegram token mount, so its five-minute credit cycle could never truthfully select Telegram.

The realtime publish warning seen from a manual `docker exec` cycle was not a durable delivery failure: the resulting in-app delivery rows were `delivered`. This hotfix therefore targets the two proven external-delivery defects rather than weakening persistence or realtime error handling.

## Fix

- Email senders now prefer `SMTP_FROM_EMAIL`, then `SMTP_USER`, then the local fallback. SMTP authentication remains unchanged.
- Both production Compose definitions give `operations-observer` the Owner Telegram token path and a read-only bind mount.
- Production activation must use a dedicated runtime copy of the Telegram token readable only by application UID/GID `1000:1000` at mode `0600`; the original root-owned secret remains unchanged.
- No Docker socket, plaintext token, token value, provider balance, or SMTP credential is added to Git, logs, notifications, or evidence.

## Verification contract

Before merge:

- SMTP regression verifies that the actual message `From` header equals `SMTP_FROM_EMAIL` while SMTP login still uses `SMTP_USER`.
- Owner SMTP test path follows the same sender rule.
- Both production Compose files validate and explicitly mount the Owner Telegram token into `operations-observer` read-only.
- Targeted tests, Ruff, Mypy, Full Backend, Core contracts, repository security, and protected GitHub CI must pass.

After merge and production activation:

- Backend, Operations Observer, and Communication Worker must be healthy with zero restarts.
- `channel_readiness()` from the live Observer and Communication Worker must report Owner Telegram ready without returning the token.
- A controlled Owner notification must produce a successful Telegram delivery receipt.
- A controlled Owner email must produce a successful email delivery receipt using the configured `SMTP_FROM_EMAIL`.
- Test notifications must be explicitly identifiable and cleaned from durable notification/delivery rows after evidence is captured.

This hotfix is not considered complete until both external channels are proven live after protected merge.
