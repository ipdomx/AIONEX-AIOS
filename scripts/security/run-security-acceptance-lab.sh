#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_TOKEN="$(printf '%s-%s' "$TIMESTAMP" "$$" | tr '[:upper:]' '[:lower:]')"
NETWORK="aionex-security-acceptance-${RUN_TOKEN}"
PG="aionex-security-acceptance-postgres-${RUN_TOKEN}"
REDIS="aionex-security-acceptance-redis-${RUN_TOKEN}"
FIXTURE="aionex-security-acceptance-fixture-${RUN_TOKEN}"
ZAP="aionex-security-acceptance-zap-${RUN_TOKEN}"
TLS="aionex-security-acceptance-tls-${RUN_TOKEN}"
RUNNER="aionex-security-acceptance-runner-${RUN_TOKEN}"
PROJECT_ID="security-acceptance-lab-project"
ZAP_KEY="$(openssl rand -hex 32)"
TEST_SECRET_KEY="$(openssl rand -hex 32)"
PG_PASSWORD="$(openssl rand -hex 24)"
OWNER_PASSWORD="$(openssl rand -base64 24 | tr -d '\n')"
STATE_ROOT="/root/.config/aionex/releases/security-acceptance-${TIMESTAMP}"
SOURCE_ROOT="${STATE_ROOT}/security-sources"
REPORT_ROOT="${STATE_ROOT}/report"
REPORT_FILE="${REPORT_ROOT}/report.json"
TOOL_CACHE="${STATE_ROOT}/tool-cache"
TLS_ROOT="${STATE_ROOT}/tls"

cleanup() {
  docker rm -f "$RUNNER" "$ZAP" "$TLS" "$FIXTURE" "$REDIS" "$PG" >/dev/null 2>&1 || true
  ids="$(docker ps -aq --filter network="$NETWORK" 2>/dev/null || true)"
  if [[ -n "$ids" ]]; then
    docker rm -f $ids >/dev/null 2>&1 || true
  fi
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
mkdir -p "$SOURCE_ROOT" "$REPORT_ROOT" "$TOOL_CACHE" "$TOOL_CACHE/tmp" "$TLS_ROOT"
chown -R 1000:1000 "$STATE_ROOT" "$SOURCE_ROOT" "$REPORT_ROOT" "$TOOL_CACHE" "$TLS_ROOT"
chmod 700 "$STATE_ROOT" "$SOURCE_ROOT" "$REPORT_ROOT" "$TOOL_CACHE" "$TOOL_CACHE/tmp" "$TLS_ROOT"
openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
  -keyout "$TLS_ROOT/key.pem" -out "$TLS_ROOT/cert.pem" \
  -subj "/CN=${TLS}" -addext "subjectAltName=DNS:${TLS}" >/dev/null 2>&1
chown 1000:1000 "$TLS_ROOT/key.pem" "$TLS_ROOT/cert.pem"
chmod 600 "$TLS_ROOT/key.pem" "$TLS_ROOT/cert.pem"

docker compose \
  --env-file web-dashboard/.env.production.example \
  -f web-dashboard/docker-compose.production.yml \
  build security-scan-worker >/dev/null

docker network create "$NETWORK" >/dev/null

docker run -d --name "$PG" --network "$NETWORK" \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD="$PG_PASSWORD" \
  -e POSTGRES_DB=aionex_acceptance \
  postgres:16-alpine >/dev/null

docker run -d --name "$REDIS" --network "$NETWORK" redis:7-alpine >/dev/null

docker run -d --name "$FIXTURE" --network "$NETWORK" \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  -v "$ROOT/web-dashboard/backend/tests/security_acceptance_lab/runtime_fixture.py:/fixture/runtime_fixture.py:ro" \
  python:3.11-slim-bookworm python /fixture/runtime_fixture.py >/dev/null

docker run -d --name "$TLS" --network "$NETWORK" \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  -v "$TLS_ROOT:/tls:ro" \
  aionex-aios-security-tools:local \
  openssl s_server -quiet -accept 8443 -cert /tls/cert.pem -key /tls/key.pem -www >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$TLS" sh -c "printf '\n' | openssl s_client -connect 127.0.0.1:8443 -servername '$TLS' >/dev/null 2>&1"; then break; fi
  sleep 1
done
docker exec "$TLS" sh -c "printf '\n' | openssl s_client -connect 127.0.0.1:8443 -servername '$TLS' >/dev/null 2>&1"

docker run -d --name "$ZAP" --network "$NETWORK" \
  --read-only --memory 3g --cpus 1.5 \
  --tmpfs /tmp:rw,noexec,nosuid,size=128m \
  --tmpfs /home/zap/.ZAP:rw,nosuid,uid=1000,gid=1000,mode=0700,size=1g \
  --tmpfs /home/zap/.java:rw,nosuid,uid=1000,gid=1000,mode=0700,size=16m \
  --tmpfs /home/zap/.mozilla:rw,nosuid,uid=1000,gid=1000,mode=0700,size=128m \
  -e ZAP_KEY="$ZAP_KEY" \
  zaproxy/zap-stable:2.17.0 \
  sh -ceu 'printf "%s\n" "-Xmx1024m" > /home/zap/.ZAP/.ZAP_JVM.properties; exec zap.sh -daemon -host 0.0.0.0 -port 8080 -config "api.key=$ZAP_KEY" -config "api.addrs.addr.name=.*" -config api.addrs.addr.regex=true -silent -notel' >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$PG" psql -U postgres -d aionex_acceptance -Atqc 'SELECT 1' 2>/dev/null | grep -qx '1'; then break; fi
  sleep 1
done
test "$(docker exec "$PG" psql -U postgres -d aionex_acceptance -Atqc 'SELECT 1')" = "1"

for _ in $(seq 1 30); do
  if docker exec "$REDIS" redis-cli ping 2>/dev/null | grep -q PONG; then break; fi
  sleep 1
done
test "$(docker exec "$REDIS" redis-cli ping)" = "PONG"

for _ in $(seq 1 30); do
  if docker exec "$FIXTURE" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/health',timeout=2).read()" >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$FIXTURE" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/health',timeout=2).read()" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$ZAP" sh -c "wget -qO- 'http://127.0.0.1:8080/JSON/core/view/version/?apikey=${ZAP_KEY}'" >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$ZAP" sh -c "wget -qO- 'http://127.0.0.1:8080/JSON/core/view/version/?apikey=${ZAP_KEY}'" >/dev/null

COMMON_ENV=(
  -e ENVIRONMENT=test
  -e DEBUG=false
  -e SECRET_KEY="$TEST_SECRET_KEY"
  -e DATABASE_URL=postgresql+asyncpg://postgres:${PG_PASSWORD}@${PG}:5432/aionex_acceptance
  -e POSTGRES_HOST=${PG}
  -e POSTGRES_PORT=5432
  -e POSTGRES_USER=postgres
  -e POSTGRES_PASSWORD="$PG_PASSWORD"
  -e POSTGRES_DB=aionex_acceptance
  -e REDIS_URL=redis://${REDIS}:6379/0
  -e AIOS_BOOTSTRAP_OWNER_EMAIL=acceptance-owner@aionex.local
  -e AIOS_BOOTSTRAP_OWNER_PASSWORD="$OWNER_PASSWORD"
  -e AIOS_BOOTSTRAP_RESET_OWNER_PASSWORD="$OWNER_PASSWORD"
  -e AIOS_SEMGREP_RULESET=/app/security-rules/semgrep/aionex.yml
  -e AIOS_NUCLEI_TEMPLATES=/workspace/web-dashboard/backend/tests/security_acceptance_lab/nuclei
  -e SECURITY_ZAP_URL=http://${ZAP}:8080
  -e SECURITY_ZAP_API_KEY=${ZAP_KEY}
  -e AIONEX_ACCEPTANCE_ORIGIN=http://${FIXTURE}:8088
  -e AIONEX_ACCEPTANCE_HOST=${FIXTURE}
  -e AIONEX_ACCEPTANCE_PROJECT_ID=${PROJECT_ID}
  -e AIONEX_ACCEPTANCE_TLS_ORIGIN=https://${TLS}:8443
  -e AIONEX_ACCEPTANCE_TLS_HOST=${TLS}
  -e AIONEX_ACCEPTANCE_SOURCE_ROOT=/var/lib/aionex/security-sources
  -e AIONEX_ACCEPTANCE_WORKSPACE=/workspace
  -e AIONEX_ACCEPTANCE_REPORT=/var/lib/aionex/security-acceptance/report.json
  -e PYTHONPATH=/workspace/src:/workspace/web-dashboard/backend:/app
  -e HOME=/tmp/aionex-security-home
  -e TMPDIR=/tmp/aionex-security-home/tmp
)
COMMON_MOUNTS=(
  -v "$ROOT:/workspace:ro"
  -v "$SOURCE_ROOT:/var/lib/aionex/security-sources:rw"
  -v "$REPORT_ROOT:/var/lib/aionex/security-acceptance:rw"
  -v "$TOOL_CACHE:/tmp/aionex-security-home:rw"
  --tmpfs /tmp:rw,nosuid,size=256m
)

# Pre-warm vulnerability databases into the same writable cache used by the
# scanner process. This separates advisory-database acquisition from detection
# and proves the read-only scanner runtime can reuse a durable cache.
docker run --rm --network "$NETWORK" \
  "${COMMON_ENV[@]}" "${COMMON_MOUNTS[@]}" \
  -w /workspace/web-dashboard/backend \
  aionex-aios-security-tools:local sh -ceu '
    trivy fs --format json --scanners vuln --exit-code 0 --no-progress /workspace/web-dashboard/backend/tests/security_acceptance_lab/fixtures/vulnerable >/dev/null
    grype dir:/workspace/web-dashboard/backend/tests/security_acceptance_lab/fixtures/vulnerable -o json >/dev/null
  '

docker run --rm --network "$NETWORK" \
  "${COMMON_ENV[@]}" "${COMMON_MOUNTS[@]}" \
  -w /workspace/web-dashboard/backend \
  aionex-aios-security-tools:local \
  alembic upgrade head >/dev/null

docker rm -f "$RUNNER" >/dev/null 2>&1 || true
docker run -d --name "$RUNNER" --network "$NETWORK" \
  "${COMMON_ENV[@]}" "${COMMON_MOUNTS[@]}" \
  -w /workspace/web-dashboard/backend \
  aionex-aios-security-tools:local \
  python scripts/security_acceptance_lab.py >/dev/null

runner_code="$(docker wait "$RUNNER")"
docker logs "$RUNNER"
if [[ "$runner_code" != "0" ]]; then
  echo "Security acceptance runner failed with exit code $runner_code" >&2
  exit "$runner_code"
fi

test -s "$REPORT_FILE"
python3 - "$REPORT_FILE" <<'PY'
import json, sys
path=sys.argv[1]
report=json.load(open(path, encoding='utf-8'))
assert report['status'] == 'PASS'
assert report['production_modified'] is False
assert report['dns_modified'] is False
assert report['external_target_used'] is False
assert report['vulnerable_scan']['required_detection_coverage'] == 1.0
assert report['vulnerable_scan']['unexpected_engine_failures'] == []
assert report['tool_smoke']['testssl']['status'] == 'completed'
assert report['tool_smoke']['testssl']['exit_code'] == 0
assert report['behavioral_validation']['status'] == 'PASS'
assert report['repeatability']['required_matrix_identical'] is True
assert report['repeatability']['deterministic_fingerprints_identical'] is True
assert report['learning_cycle']['status'] == 'promoted'
assert report['remediation_cycle']['status'] == 'verified_fixed'
assert report['remediation_cycle']['residual_high_medium'] == []
assert report['remediation_cycle']['unexpected_engine_failures'] == []
assert report['initial_release_gate']['decision'] == 'blocked'
assert report['final_release_gate']['decision'] == 'passed'
print(json.dumps({
    'status': report['status'],
    'coverage': report['vulnerable_scan']['required_detection_coverage'],
    'vulnerable_findings': report['vulnerable_scan']['finding_count'],
    'repeatable': report['repeatability']['deterministic_fingerprints_identical'],
    'learning': report['learning_cycle']['status'],
    'remediation': report['remediation_cycle']['status'],
    'final_gate': report['final_release_gate']['decision'],
    'report': path,
}, sort_keys=True))
PY

trap - EXIT
cleanup
printf '%s\n' "$REPORT_FILE"
