#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
IMAGE=${AIOS_ANDROID_BUILDER_IMAGE:-aionex-android-builder:36}
RELEASE_DIR=${AIOS_MOBILE_RELEASE_DIR:-/root/.config/aionex/releases}
KEYSTORE=${AIOS_ANDROID_KEYSTORE_FILE:-/root/.config/aionex/mobile/android-release.jks}
CREDENTIAL_FILE=${AIOS_ANDROID_CREDENTIAL_FILE:-/root/.config/aionex/mobile/android-release.env}

install -d -m 0700 "$(dirname "$KEYSTORE")" "$RELEASE_DIR"
python3 "$ROOT/scripts/mobile/prepare_android_assets.py"
if [[ ! -f "$CREDENTIAL_FILE" ]]; then
  umask 077
  store_password=$(openssl rand -base64 36 | tr -d '\r\n')
  printf 'STORE_PASSWORD=%s\nKEY_PASSWORD=%s\nKEY_ALIAS=aionex\n' \
    "$store_password" "$store_password" > "$CREDENTIAL_FILE"
  chmod 0600 "$CREDENTIAL_FILE"
fi
# shellcheck disable=SC1090
source "$CREDENTIAL_FILE"
# Java's default PKCS12 keystore uses the store password for the private key.
KEY_PASSWORD="$STORE_PASSWORD"
if [[ ! -f "$KEYSTORE" ]]; then
  docker run --rm \
    -v "$(dirname "$KEYSTORE"):/keys" \
    "$IMAGE" keytool -genkeypair -v \
      -keystore "/keys/$(basename "$KEYSTORE")" \
      -storepass "$STORE_PASSWORD" \
      -keypass "$KEY_PASSWORD" \
      -alias "$KEY_ALIAS" \
      -keyalg RSA -keysize 4096 -validity 10000 \
      -dname "CN=AIONEX AIOS, OU=Mobile, O=AIONEX, L=Dubai, ST=Dubai, C=AE"
  chmod 0600 "$KEYSTORE"
fi

docker run --rm \
  -v "$ROOT:/workspace" \
  -v "$KEYSTORE:/keys/android-release.jks:ro" \
  -w /workspace/mobile/android \
  -e AIOS_ANDROID_KEYSTORE_FILE=/keys/android-release.jks \
  -e AIOS_ANDROID_KEYSTORE_PASSWORD="$STORE_PASSWORD" \
  -e AIOS_ANDROID_KEY_ALIAS="$KEY_ALIAS" \
  -e AIOS_ANDROID_KEY_PASSWORD="$KEY_PASSWORD" \
  "$IMAGE" ./gradlew --no-daemon clean lintRelease assembleRelease bundleRelease

APK="$ROOT/mobile/android/app/build/outputs/apk/release/app-release.apk"
AAB="$ROOT/mobile/android/app/build/outputs/bundle/release/app-release.aab"
test -s "$APK" && test -s "$AAB"
install -m 0600 "$APK" "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.apk"
install -m 0600 "$AAB" "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.aab"
sha256sum \
  "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.apk" \
  "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.aab" \
  > "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.sha256"
chmod 0600 "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.sha256"

CERT_SHA256=$(docker run --rm \
  -v "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.apk:/release/app.apk:ro" \
  "$IMAGE" sh -lc \
  '/opt/android-sdk/build-tools/36.0.0/apksigner verify --print-certs /release/app.apk' \
  | sed -n 's/^Signer #1 certificate SHA-256 digest: //p' | head -n 1)
test -n "$CERT_SHA256"
EXPECTED_CERT_SHA256=$(python3 - "$ROOT/vip-frontend/public/.well-known/assetlinks.json" <<'PYVERIFY'
import json, sys
payload=json.load(open(sys.argv[1],encoding='utf-8'))
print(payload[0]['target']['sha256_cert_fingerprints'][0].replace(':','').lower())
PYVERIFY
)
if [[ "${CERT_SHA256,,}" != "$EXPECTED_CERT_SHA256" ]]; then
  echo "Android release certificate does not match assetlinks.json" >&2
  exit 1
fi

APK_SHA256=$(sha256sum "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.apk" | awk '{print $1}')
AAB_SHA256=$(sha256sum "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.aab" | awk '{print $1}')
export APK_SHA256 AAB_SHA256 CERT_SHA256 RELEASE_DIR
python3 - <<'PYMETA'
import json, os
from pathlib import Path
root=Path(os.environ['RELEASE_DIR'])
payload={
    'schema_version': 1,
    'application_id': 'net.vipe.aionex',
    'version_name': '1.0.0',
    'version_code': 1,
    'minimum_sdk': 27,
    'target_sdk': 36,
    'apk_sha256': os.environ['APK_SHA256'],
    'aab_sha256': os.environ['AAB_SHA256'],
    'signing_certificate_sha256': os.environ['CERT_SHA256'].lower(),
    'portal_url': 'https://ai.vip-e.net/ar/',
    'cleartext_traffic_allowed': False,
    'signing_secret_returned': False,
}
path=root/'AIONEX-AIOS-Android-v1.0.0-release.json'
path.write_text(json.dumps(payload,sort_keys=True,indent=2)+'\n',encoding='utf-8')
path.chmod(0o600)
PYMETA

printf 'ANDROID_APK=%s\nANDROID_AAB=%s\nANDROID_CERT_SHA256=%s\n' \
  "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.apk" \
  "$RELEASE_DIR/AIONEX-AIOS-Android-v1.0.0.aab" \
  "$CERT_SHA256"
