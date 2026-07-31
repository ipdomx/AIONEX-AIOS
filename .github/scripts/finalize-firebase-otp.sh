#!/usr/bin/env bash
set -Eeuo pipefail

core=/tmp/finalize-firebase-otp-core.sh
curl --fail --silent --show-error --location \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/${GITHUB_REPOSITORY}/git/blobs/50101c1a905505d823bd545ab938ec53e4227668" \
  | jq -r '.content' \
  | tr -d '\r\n ' \
  | base64 --decode > "$core"

python - "$core" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
start = text.index("test -f web-dashboard/secrets/.gitignore")
end = text.index("\nrm -f .github/workflows/one-shot-firebase-source-snapshot.yml", start)
replacement = r'''test -f web-dashboard/secrets/.gitignore
test "$(find web-dashboard/secrets -mindepth 1 -maxdepth 1 -type f ! -name .gitignore | wc -l)" = "0"
test -z "$(git ls-files 'web-dashboard/secrets/*' | grep -v '^web-dashboard/secrets/.gitignore$' || true)"
if git grep -I -n 'BEGIN PRIVATE KEY' -- \
  ':!web-dashboard/backend/tests/*' \
  ':!.github/scripts/finalize-firebase-otp.sh' \
  ':!.github/workflows/finalize-firebase-otp-integration.yml' \
  ':!.github/workflows/finalize-firebase-otp-v2.yml'
then
  exit 1
fi
if git grep -I -n -E '"private_key"[[:space:]]*:[[:space:]]*"-----BEGIN' -- \
  ':!web-dashboard/backend/tests/*'
then
  exit 1
fi
'''
path.write_text(text[:start] + replacement + text[end:])
PY

chmod 0755 "$core"
exec "$core"
