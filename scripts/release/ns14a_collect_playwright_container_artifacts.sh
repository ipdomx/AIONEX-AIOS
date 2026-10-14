#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

test "$(id -u)" = "0"
test "$(hostname)" = "nc-ph-4354"
test "$#" -ge 2
test "$#" -le 3
runner="$1"
evidence_dir="$2"
report_in_container="${3:-/tmp/playwright-results.json}"
case "$runner" in
  aionex-ns14a-*) ;;
  *) echo "REFUSE_UNSCOPED_RUNNER" >&2; exit 64 ;;
esac
case "$evidence_dir" in
  /var/lib/aionex-migration/r1-management-20261008/*) ;;
  *) echo "REFUSE_OUTSIDE_EVIDENCE_ROOT" >&2; exit 64 ;;
esac
# Deny traversal, symlinked directories and arbitrary container file extraction.
test "$(realpath -m -- "$evidence_dir")" = "$evidence_dir"
test "$report_in_container" = "/tmp/playwright-results.json"
test ! -L "$evidence_dir"
test "$(docker inspect "$runner" --format '{{index .Config.Labels "aionex.acceptance.scope"}}')" = "ns14a"
test "$(docker inspect "$runner" --format '{{.State.Running}}')" = "false"

mkdir -p "$evidence_dir/test-results"
chmod 0700 "$evidence_dir" "$evidence_dir/test-results"
timeout 45 docker cp "$runner:$report_in_container" "$evidence_dir/PLAYWRIGHT-RESULTS.json"
timeout 90 docker cp "$runner:/test-results/." "$evidence_dir/test-results/"
chmod -R go-rwx "$evidence_dir"

guard_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$guard_dir/ns14a_validate_playwright_artifacts.py" \
  "$evidence_dir/PLAYWRIGHT-RESULTS.json" "$evidence_dir" --expected-tests 6 \
  > "$evidence_dir/PLAYWRIGHT-ARTIFACT-RETENTION-AUDIT.json"
sha256sum "$evidence_dir/PLAYWRIGHT-RESULTS.json"   "$evidence_dir/PLAYWRIGHT-ARTIFACT-RETENTION-AUDIT.json"   > "$evidence_dir/PLAYWRIGHT-EVIDENCE-SHA256SUMS.txt"

# Cleanup is deliberately last and is unreachable when retention validation fails.
docker rm "$runner"
echo "PLAYWRIGHT_EVIDENCE_RETAINED_BEFORE_RUNNER_REMOVAL"
