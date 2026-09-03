#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-deploy/production/.env.payments}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing payments environment file: $ENV_FILE" >&2
  exit 1
fi

read_value() {
  local key="$1"
  local value
  value="$(awk -v wanted="$key" '
    index($0, "#") == 1 { next }
    {
      pos = index($0, "=")
      if (pos == 0) next
      key = substr($0, 1, pos - 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
      if (key == wanted) result = substr($0, pos + 1)
    }
    END { print result }
  ' "$ENV_FILE")"
  value="${value#\"}"; value="${value%\"}"
  value="${value#\'}"; value="${value%\'}"
  printf '%s' "$value"
}

value_or_default() {
  local key="$1" default="$2" value
  value="$(read_value "$key")"
  printf '%s' "${value:-$default}"
}

require_all_or_none() {
  local label="$1"
  shift
  local key value any=false missing=()
  for key in "$@"; do
    value="$(read_value "$key")"
    [[ -n "$value" ]] && any=true
  done
  if [[ "$any" == true ]]; then
    for key in "$@"; do
      value="$(read_value "$key")"
      [[ -z "$value" ]] && missing+=("$key")
    done
  fi
  if ((${#missing[@]})); then
    echo "$label configuration is incomplete; missing: ${missing[*]}" >&2
    exit 1
  fi
}

validate_optional_bool() {
  local key="$1" value
  value="$(read_value "$key")"
  [[ -z "$value" ]] && return 0
  if [[ "$value" != "true" && "$value" != "false" ]]; then
    echo "$key must be true or false when supplied" >&2
    exit 1
  fi
}

payments_environment="$(read_value PAYMENTS_ENVIRONMENT)"
[[ -z "$payments_environment" ]] && payments_environment="$(read_value PAYMENTS_ENV)"
payments_environment="${payments_environment:-sandbox}"
case "$payments_environment" in
  sandbox|test|live|production) ;;
  *) echo "PAYMENTS_ENVIRONMENT must be sandbox, test, live, or production" >&2; exit 1 ;;
esac

currency="$(value_or_default PAYMENTS_DEFAULT_CURRENCY USD)"
if [[ ! "$currency" =~ ^[A-Za-z]{3}$ ]]; then
  echo "PAYMENTS_DEFAULT_CURRENCY must be a 3-letter currency code" >&2
  exit 1
fi

success_url="$(value_or_default PAYMENTS_SUCCESS_URL 'https://ai.vip-e.net/en/billing?checkout=success')"
cancel_url="$(value_or_default PAYMENTS_CANCEL_URL 'https://ai.vip-e.net/en/billing?checkout=cancelled')"
[[ "$success_url" == https://* ]] || { echo "PAYMENTS_SUCCESS_URL must use HTTPS" >&2; exit 1; }
[[ "$cancel_url" == https://* ]] || { echo "PAYMENTS_CANCEL_URL must use HTTPS" >&2; exit 1; }

tolerance="$(value_or_default PAYMENTS_WEBHOOK_TOLERANCE_SECONDS 300)"
if [[ ! "$tolerance" =~ ^[0-9]+$ ]] || (( tolerance < 30 || tolerance > 3600 )); then
  echo "PAYMENTS_WEBHOOK_TOLERANCE_SECONDS must be an integer from 30 to 3600" >&2
  exit 1
fi

require_all_or_none "Stripe" STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET
require_all_or_none "PayPal" PAYPAL_CLIENT_ID PAYPAL_CLIENT_SECRET PAYPAL_WEBHOOK_ID
require_all_or_none "Paddle" PADDLE_API_KEY PADDLE_WEBHOOK_SECRET
require_all_or_none "Paymob" PAYMOB_API_KEY PAYMOB_WEBHOOK_SECRET
require_all_or_none "Fawry" FAWRY_API_KEY FAWRY_WEBHOOK_SECRET
require_all_or_none "STC Pay" STC_PAY_API_KEY STC_PAY_WEBHOOK_SECRET
require_all_or_none "Bank transfer" BANK_TRANSFER_BANK_NAME BANK_TRANSFER_ACCOUNT_NAME BANK_TRANSFER_IBAN

stripe_key="$(read_value STRIPE_SECRET_KEY)"
if [[ "$payments_environment" == "live" || "$payments_environment" == "production" ]]; then
  if [[ "$stripe_key" == sk_test_* || "$stripe_key" == rk_test_* ]]; then
    echo "Live payments must not use a Stripe test key" >&2
    exit 1
  fi
fi

for flag in GOOGLE_PAY_ENABLED MADA_ENABLED APPLE_PAY_ENABLED PAYMENTS_ALLOW_TEST_KEYS; do
  validate_optional_bool "$flag"
done

if [[ "$(read_value GOOGLE_PAY_ENABLED)" == "true" || "$(read_value MADA_ENABLED)" == "true" ]]; then
  [[ -n "$stripe_key" && -n "$(read_value STRIPE_WEBHOOK_SECRET)" ]] || {
    echo "Google Pay and Mada require the configured Stripe adapter" >&2
    exit 1
  }
fi

# AIOS intentionally keeps the requested direct Apple Pay gateway outside the
# Stripe adapter. Until a Merchant ID, domain association, payment-processing
# certificate, and non-Stripe settlement processor/adapter are selected and
# implemented, activation must remain fail-closed rather than silently routing
# Apple Pay through Stripe.
if [[ "$(read_value APPLE_PAY_ENABLED)" == "true" ]]; then
  echo "Direct Apple Pay is an external activation boundary: configure an Apple Merchant ID, verified domain, payment-processing certificate, and selected non-Stripe settlement processor/adapter before enabling it" >&2
  exit 1
fi

if [[ "$payments_environment" == "live" || "$payments_environment" == "production" ]]; then
  if [[ "$(read_value PAYMENTS_ALLOW_TEST_KEYS)" == "true" ]]; then
    echo "Live payments must reject test keys" >&2
    exit 1
  fi
fi

echo "Payments environment configuration is valid for the current AIOS payment contract."
