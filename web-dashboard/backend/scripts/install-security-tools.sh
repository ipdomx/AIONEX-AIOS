#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$(dpkg --print-architecture)" != "amd64" ]]; then
  echo "AIONEX security-tools image currently supports the production amd64 runtime only." >&2
  exit 1
fi

NUCLEI_VERSION=3.11.1
NUCLEI_TEMPLATES_VERSION=10.4.7
NUCLEI_TEMPLATES_SHA256=a84dffa24f6a6e44798f45a4502f9cb06f93714287bce75a5fc559e153252f7e
KATANA_VERSION=1.7.0
HTTPX_VERSION=1.10.0
TRIVY_VERSION=0.73.0
OSV_VERSION=2.5.0
SYFT_VERSION=1.50.0
GRYPE_VERSION=0.116.1
GITLEAKS_VERSION=8.30.1
COSIGN_VERSION=3.1.3
TRUFFLEHOG_VERSION=3.96.0
TESTSSL_VERSION=3.2.4
TESTSSL_SHA256=e5f3dba2be42dc7efab0d5e70d25aec43c447552b5dfb8a3587f4440d3b5f4ee
NIKTO_VERSION=2.6.1
NIKTO_SHA256=0d710a0cf9378a4b6f563cb1165a797d64d6841fe3cb1a3e3cb0ae2d7eac9962

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

download() {
  local output="$1" url="$2"
  local attempt=1 delay=2 max_attempts=8

  while (( attempt <= max_attempts )); do
    if curl \
      --fail \
      --silent \
      --show-error \
      --location \
      --retry 2 \
      --retry-delay 1 \
      --retry-all-errors \
      --connect-timeout 20 \
      --max-time 120 \
      --output "$output" \
      "$url"; then
      return 0
    fi

    rm -f "$output"
    if (( attempt == max_attempts )); then
      echo "Download failed after ${max_attempts} attempts: ${output}" >&2
      return 1
    fi

    echo "Transient download failure for ${output}; retrying in ${delay}s" >&2
    sleep "$delay"
    delay=$((delay * 2))
    if (( delay > 60 )); then
      delay=60
    fi
    attempt=$((attempt + 1))
  done
}

verify_asset() {
  local checksums="$1" asset="$2"
  local expected
  expected="$(awk -v asset="$asset" '{name=$2; sub(/^\*/, "", name); if (name == asset) {print $1; exit}}' "$checksums")"
  [[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || { echo "Checksum for $asset was not found" >&2; exit 1; }
  printf '%s  %s\n' "$expected" "$work/$asset" | sha256sum -c -
}

install_zip_release() {
  local repo="$1" version="$2" asset="$3" checksum_asset="$4" binary="$5"
  local base="https://github.com/$repo/releases/download/v$version"
  download "$asset" "$base/$asset"
  download "$checksum_asset" "$base/$checksum_asset"
  verify_asset "$checksum_asset" "$asset"
  unzip -q "$asset" "$binary"
  install -m 0755 "$binary" "/usr/local/bin/$binary"
}

install_tgz_release() {
  local repo="$1" tag="$2" version="$3" asset="$4" checksum_asset="$5" binary="$6"
  local base="https://github.com/$repo/releases/download/$tag"
  download "$asset" "$base/$asset"
  download "$checksum_asset" "$base/$checksum_asset"
  verify_asset "$checksum_asset" "$asset"
  tar -xzf "$asset" "$binary"
  install -m 0755 "$binary" "/usr/local/bin/$binary"
}

install_zip_release projectdiscovery/nuclei "$NUCLEI_VERSION" "nuclei_${NUCLEI_VERSION}_linux_amd64.zip" "nuclei_${NUCLEI_VERSION}_checksums.txt" nuclei
download nuclei-templates.tar.gz "https://api.github.com/repos/projectdiscovery/nuclei-templates/tarball/v${NUCLEI_TEMPLATES_VERSION}"
printf '%s  %s\n' "$NUCLEI_TEMPLATES_SHA256" nuclei-templates.tar.gz | sha256sum -c -
mkdir -p /opt/nuclei-templates
tar -xzf nuclei-templates.tar.gz --strip-components=1 -C /opt/nuclei-templates
install_zip_release projectdiscovery/katana "$KATANA_VERSION" "katana_${KATANA_VERSION}_linux_amd64.zip" "katana-${KATANA_VERSION}-checksums.txt" katana
install_zip_release projectdiscovery/httpx "$HTTPX_VERSION" "httpx_${HTTPX_VERSION}_linux_amd64.zip" "httpx_${HTTPX_VERSION}_checksums.txt" httpx
mv /usr/local/bin/httpx /usr/local/bin/pd-httpx

asset="trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"
checksums="trivy_${TRIVY_VERSION}_checksums.txt"
download "$asset" "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/$asset"
download "$checksums" "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/$checksums"
verify_asset "$checksums" "$asset"
tar -xzf "$asset" trivy
install -m 0755 trivy /usr/local/bin/trivy

asset="osv-scanner_linux_amd64"
checksums="osv-scanner_SHA256SUMS"
download "$asset" "https://github.com/google/osv-scanner/releases/download/v${OSV_VERSION}/$asset"
download "$checksums" "https://github.com/google/osv-scanner/releases/download/v${OSV_VERSION}/$checksums"
verify_asset "$checksums" "$asset"
install -m 0755 "$asset" /usr/local/bin/osv-scanner

install_tgz_release anchore/syft "v${SYFT_VERSION}" "$SYFT_VERSION" "syft_${SYFT_VERSION}_linux_amd64.tar.gz" "syft_${SYFT_VERSION}_checksums.txt" syft
install_tgz_release anchore/grype "v${GRYPE_VERSION}" "$GRYPE_VERSION" "grype_${GRYPE_VERSION}_linux_amd64.tar.gz" "grype_${GRYPE_VERSION}_checksums.txt" grype
install_tgz_release gitleaks/gitleaks "v${GITLEAKS_VERSION}" "$GITLEAKS_VERSION" "gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" "gitleaks_${GITLEAKS_VERSION}_checksums.txt" gitleaks
install_tgz_release trufflesecurity/trufflehog "v${TRUFFLEHOG_VERSION}" "$TRUFFLEHOG_VERSION" "trufflehog_${TRUFFLEHOG_VERSION}_linux_amd64.tar.gz" "trufflehog_${TRUFFLEHOG_VERSION}_checksums.txt" trufflehog

asset=cosign-linux-amd64
checksums=cosign_checksums.txt
download "$asset" "https://github.com/sigstore/cosign/releases/download/v${COSIGN_VERSION}/$asset"
download "$checksums" "https://github.com/sigstore/cosign/releases/download/v${COSIGN_VERSION}/$checksums"
verify_asset "$checksums" "$asset"
install -m 0755 "$asset" /usr/local/bin/cosign

download testssl.tar.gz "https://api.github.com/repos/testssl/testssl.sh/tarball/v${TESTSSL_VERSION}"
printf '%s  %s\n' "$TESTSSL_SHA256" testssl.tar.gz | sha256sum -c -
mkdir -p /opt/testssl
tar -xzf testssl.tar.gz --strip-components=1 -C /opt/testssl
ln -s /opt/testssl/testssl.sh /usr/local/bin/testssl.sh

download nikto.tar.gz "https://api.github.com/repos/sullo/nikto/tarball/${NIKTO_VERSION}"
printf '%s  %s\n' "$NIKTO_SHA256" nikto.tar.gz | sha256sum -c -
mkdir -p /opt/nikto
tar -xzf nikto.tar.gz --strip-components=1 -C /opt/nikto
ln -s /opt/nikto/program/nikto.pl /usr/local/bin/nikto
chmod 0755 /opt/nikto/program/nikto.pl

# Fail the image build if any pinned binary was not installed.
for binary in nuclei katana pd-httpx trivy osv-scanner syft grype gitleaks trufflehog cosign testssl.sh nikto; do
  command -v "$binary" >/dev/null
 done
