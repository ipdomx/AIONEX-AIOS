#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/deploy/payments/.env.sandbox}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing sandbox environment file: $ENV_FILE" >&2
  exit 1
fi

required=(
  PAYMENTS_ENV
  PAYMENTS_DEFAULT_CURRENCY
  PAYMENTS_SUCCESS_URL
  PAYMENTS_CANCEL_URL
  STRIPE_SECRET_KEY
  STRIPE_PUBLISHABLE_KEY
  STRIPE_WEBHOOK_SECRET
  PAYPAL_CLIENT_ID
  PAYPAL_CLIENT_SECRET
  PAYPAL_WEBHOOK_ID
  PADDLE_API_KEY
  PADDLE_CLIENT_TOKEN
  PADDLE_WEBHOOK_SECRET
)

for key in "${required[@]}"; do
  value="$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-)"
  if [[ -z "$value" ]]; then
    echo "Missing required sandbox variable: $key" >&2
    exit 1
  fi
done

if ! grep -q '^PAYMENTS_ENV=sandbox$' "$ENV_FILE"; then
  echo "PAYMENTS_ENV must be sandbox." >&2
  exit 1
fi

if ! grep -q '^PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com$' "$ENV_FILE"; then
  echo "PAYPAL_BASE_URL must point to PayPal sandbox." >&2
  exit 1
fi

if ! grep -q '^PADDLE_ENV=sandbox$' "$ENV_FILE"; then
  echo "PADDLE_ENV must be sandbox." >&2
  exit 1
fi

echo "Payments sandbox configuration validated."
