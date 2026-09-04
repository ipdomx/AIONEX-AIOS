#!/usr/bin/env bash
set -euo pipefail

max_attempts="${NPM_AUDIT_MAX_ATTEMPTS:-4}"
base_delay_seconds="${NPM_AUDIT_RETRY_DELAY_SECONDS:-15}"
attempt=1

is_transient_registry_error() {
  local file="$1"
  grep -Eqi '(^|[^0-9])(429 Too Many Requests|5[0-9]{2} (Bad Gateway|Service Unavailable|Gateway Timeout|Internal Server Error)|EAI_AGAIN|ECONNRESET|ETIMEDOUT|ENETUNREACH|ECONNREFUSED|socket hang up|fetch failed|audit endpoint returned an error)([^0-9]|$)' "$file"
}

while (( attempt <= max_attempts )); do
  output_file="$(mktemp)"
  set +e
  NPM_CONFIG_FETCH_TIMEOUT="${NPM_AUDIT_FETCH_TIMEOUT_MS:-60000}" \
  NPM_CONFIG_FETCH_RETRIES="${NPM_AUDIT_FETCH_RETRIES:-1}" \
    npm audit --omit=dev >"$output_file" 2>&1
  status=$?
  set -e

  cat "$output_file"

  if (( status == 0 )); then
    rm -f "$output_file"
    exit 0
  fi

  if ! is_transient_registry_error "$output_file"; then
    rm -f "$output_file"
    exit "$status"
  fi

  if (( attempt == max_attempts )); then
    echo "npm audit failed after ${max_attempts} attempts because the registry/audit service remained unavailable." >&2
    rm -f "$output_file"
    exit "$status"
  fi

  delay=$((base_delay_seconds * attempt))
  echo "Transient npm audit service/network error detected; retrying in ${delay}s (attempt ${attempt}/${max_attempts})." >&2
  rm -f "$output_file"
  sleep "$delay"
  attempt=$((attempt + 1))
done
