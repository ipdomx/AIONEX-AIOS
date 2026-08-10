#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-deploy/production/.env.payments}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing payments environment file: $ENV_FILE" >&2
  exit 1
fi

read_value() {
  local key="$1"
  grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-
}

require_non_empty() {
  local key="$1"
  local value
  value="$(read_value "$key")"
  if [[ -z "$value" ]]; then
    echo "Missing required value: $key" >&2
    exit 1
  fi
}

require_bool() {
  local key="$1"
  local value
  value="$(read_value "$key")"
  if [[ "$value" != "true" && "$value" != "false" ]]; then
    echo "$key must be true or false" >&2
    exit 1
  fi
}

require_non_empty PAYMENTS_ENV
require_non_empty PAYMENTS_DEFAULT_CURRENCY
require_non_empty PAYMENTS_PUBLIC_ORIGIN
require_non_empty PAYMENTS_API_ORIGIN
require_bool PAYMENTS_REQUIRE_HTTPS
require_bool PAYMENTS_ALLOW_TEST_KEYS
require_bool PAYMENTS_AUDIT_LOG_ENABLED
require_bool PAYMENTS_IDEMPOTENCY_ENABLED

if [[ "$(read_value PAYMENTS_REQUIRE_HTTPS)" == "true" ]]; then
  [[ "$(read_value PAYMENTS_PUBLIC_ORIGIN)" == https://* ]] || { echo "PAYMENTS_PUBLIC_ORIGIN must use HTTPS" >&2; exit 1; }
  [[ "$(read_value PAYMENTS_API_ORIGIN)" == https://* ]] || { echo "PAYMENTS_API_ORIGIN must use HTTPS" >&2; exit 1; }
fi

validate_provider() {
  local enabled_key="$1"
  shift
  require_bool "$enabled_key"
  if [[ "$(read_value "$enabled_key")" == "true" ]]; then
    local key
    for key in "$@"; do
      require_non_empty "$key"
    done
  fi
}

validate_provider STRIPE_ENABLED STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY STRIPE_WEBHOOK_SECRET
validate_provider PAYPAL_ENABLED PAYPAL_CLIENT_ID PAYPAL_CLIENT_SECRET PAYPAL_WEBHOOK_ID
validate_provider PADDLE_ENABLED PADDLE_API_KEY PADDLE_CLIENT_TOKEN PADDLE_WEBHOOK_SECRET
validate_provider PAYMOB_ENABLED PAYMOB_API_KEY PAYMOB_HMAC_SECRET
validate_provider FAWRY_ENABLED FAWRY_MERCHANT_CODE FAWRY_SECURITY_KEY
validate_provider STC_PAY_ENABLED STC_PAY_MERCHANT_ID STC_PAY_SECRET
validate_provider MADA_ENABLED MADA_MERCHANT_ID MADA_SECRET
validate_provider BANK_TRANSFER_ENABLED BANK_TRANSFER_ACCOUNT_NAME BANK_TRANSFER_IBAN BANK_TRANSFER_BANK_NAME

if [[ "$(read_value APPLE_PAY_ENABLED)" == "true" || "$(read_value GOOGLE_PAY_ENABLED)" == "true" ]]; then
  [[ "$(read_value STRIPE_ENABLED)" == "true" ]] || { echo "Apple Pay and Google Pay require Stripe to be enabled" >&2; exit 1; }
fi

if [[ "$(read_value PAYMENTS_ENV)" == "production" && "$(read_value PAYMENTS_ALLOW_TEST_KEYS)" != "false" ]]; then
  echo "Production environment must reject test keys" >&2
  exit 1
fi

echo "Payments environment configuration is valid."
