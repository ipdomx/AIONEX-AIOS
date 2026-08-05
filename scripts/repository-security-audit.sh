#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

failures=0

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  failures=$((failures + 1))
}

tracked_matches() {
  local pattern="$1"
  git ls-files -z | while IFS= read -r -d '' file; do
    [[ "$file" =~ $pattern ]] && printf '%s\n' "$file"
  done
}

forbidden_files='(^|/)(\.env($|\.)|credentials\.json$|firebase-admin.*\.json$|service-account.*\.json$|id_rsa$|id_ed25519$)|\.(pem|key|p12|pfx|jks|keystore|kdbx|tfstate|sqlite3?|db|dump)$'
forbidden="$(tracked_matches "$forbidden_files" || true)"
if [[ -n "$forbidden" ]]; then
  fail "Tracked secret, credential, database, or state files detected:\n$forbidden"
fi

secret_pattern='(-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|sk-(proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|CLOUDFLARE_TUNNEL_TOKEN[[:space:]]*=[[:space:]]*[^[:space:]#]+)'
secret_hits="$(git grep -nEI "$secret_pattern" -- ':!*.example' ':!*.md' ':!scripts/repository-security-audit.sh' || true)"
if [[ -n "$secret_hits" ]]; then
  fail "Potential committed secret material detected:\n$secret_hits"
fi

generated_pattern='(^|/)(__pycache__|node_modules|\.next|dist|build|coverage|htmlcov|diagnostics|test-results|playwright-report)(/|$)|\.(pyc|pyo|log|tmp|swp)$'
generated="$(tracked_matches "$generated_pattern" || true)"
if [[ -n "$generated" ]]; then
  fail "Tracked generated or temporary artifacts detected:\n$generated"
fi

large_files="$(git ls-files -z | while IFS= read -r -d '' file; do
  [[ -f "$file" ]] || continue
  size="$(wc -c < "$file")"
  if (( size > 10485760 )); then
    printf '%s (%s bytes)\n' "$file" "$size"
  fi
done)"
if [[ -n "$large_files" ]]; then
  fail "Tracked files larger than 10 MiB require explicit review:\n$large_files"
fi

if (( failures > 0 )); then
  printf '\nRepository security audit failed with %d issue group(s).\n' "$failures" >&2
  exit 1
fi

printf 'Repository security audit passed.\n'
