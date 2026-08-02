#!/usr/bin/env bash
set -euo pipefail

PUBLIC_URL="${PUBLIC_URL:-https://vip-e.net}"
API_URL="${API_URL:-https://api.vip-e.net}"

curl --fail --silent --show-error --max-time 15 "$PUBLIC_URL" >/dev/null
curl --fail --silent --show-error --max-time 15 "$API_URL/health" >/dev/null

echo "Production endpoints are healthy."
