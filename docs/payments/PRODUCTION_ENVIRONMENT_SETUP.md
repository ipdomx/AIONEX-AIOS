# Payments Production Environment Setup

This step prepares the production environment variables without storing any real secret in GitHub.

## Procedure

1. Copy `deploy/production/.env.payments.example` to the server secret-managed path, or validate the existing secret-managed payment environment directly.
2. Populate only credentials for providers approved by the owner; unset/empty provider credentials remain disabled by default.
3. Enter live credentials through the server secret manager or vault.
4. Keep `PAYMENTS_ALLOW_TEST_KEYS=false` in production.
5. Keep webhook verification, audit logging, idempotency, and HTTPS enforcement enabled.
6. Validate before deployment:

```bash
bash scripts/validate-payments-env.sh /secure/path/.env.payments
```

## Required activation controls

- Google Pay uses the configured Stripe adapter. Direct Apple Pay must remain disabled until its separate Apple Merchant ID/domain/certificate and non-Stripe settlement adapter are approved and installed.
- Enabled providers must have all required credentials.
- Production origins must use HTTPS.
- Real keys must never be committed to the repository.
- Start with all providers disabled and activate one provider at a time after its sandbox test succeeds.

## Production endpoints

- Web: `https://vip-e.net`
- API: `https://api.vip-e.net`
