#!/usr/bin/env bash
# FR-06B1 isolated live-asset copy, LUKS2 recovery, and fail-closed Docker lab.
# The lab reads the eleven production asset volumes but only writes temporary
# LUKS files, mappings, mounts, Docker volumes, and containers with unique names.
set -Eeuo pipefail
umask 077

usage() {
  echo "usage: $0 --receipt /absolute/new/receipt.json" >&2
}

RECEIPT=""
if [[ "${1:-}" == "--receipt" && -n "${2:-}" && -z "${3:-}" ]]; then
  RECEIPT="$2"
else
  usage
  exit 64
fi
[[ "$RECEIPT" == /* ]] || { echo "receipt path must be absolute" >&2; exit 64; }
[[ ! -e "$RECEIPT" ]] || { echo "receipt already exists" >&2; exit 73; }
[[ "$EUID" -eq 0 ]] || { echo "FR-06B1 lab requires root" >&2; exit 77; }

for command in cryptsetup mkfs.ext4 mount umount mountpoint fallocate rsync \
  python3 docker findmnt grep sha256sum stat sync date git blkid dd awk sort \
  find install chmod chown rm cat; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 69; }
done
[[ "$(findmnt -n -o FSTYPE --target /dev/shm)" == "tmpfs" ]] || {
  echo "/dev/shm must be tmpfs so lab keys are not persisted" >&2
  exit 78
}
docker image inspect aionex-aios-backend:local >/dev/null

SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
HELPER="$SCRIPT_ROOT/scripts/security/fr06b_asset_copy_manifest.py"
[[ -f "$HELPER" && ! -L "$HELPER" ]] || { echo "manifest helper missing" >&2; exit 69; }

PASSIVE_ROOTS=(
  three_d_asset_data
  media_asset_data
  studio_asset_data
  course_package_data
  realtime_recording_data
  portal_asset_data
  mobile_release_data
  audio_song_ingress_data
  security_source_data
  security_remediation_data
)
PROJECT_ROOT="project_execution_data"
ALL_ROOTS=(
  three_d_asset_data
  media_asset_data
  project_execution_data
  studio_asset_data
  course_package_data
  realtime_recording_data
  portal_asset_data
  mobile_release_data
  audio_song_ingress_data
  security_source_data
  security_remediation_data
)

LAB_ROOT="$(mktemp -d /var/tmp/aionex-fr06b1-lab.XXXXXX)"
KEY_ROOT="$(mktemp -d /dev/shm/aionex-fr06b1-keys.XXXXXX)"
case "$LAB_ROOT" in /var/tmp/aionex-fr06b1-lab.*) ;; *) exit 78 ;; esac
case "$KEY_ROOT" in /dev/shm/aionex-fr06b1-keys.*) ;; *) exit 78 ;; esac

suffix="${LAB_ROOT##*.}"
suffix="${suffix//[^a-zA-Z0-9]/}"
ASSET_MAPPER="aionex-fr06b1-asset-${suffix}"
PROJECT_MAPPER="aionex-fr06b1-project-${suffix}"
ASSET_WRONG_MAPPER="${ASSET_MAPPER}-wrong"
PROJECT_WRONG_MAPPER="${PROJECT_MAPPER}-wrong"
ASSET_IMAGE="$LAB_ROOT/asset-vault.luks2"
PROJECT_IMAGE="$LAB_ROOT/project-execution-vault.luks2"
ASSET_MOUNT="$LAB_ROOT/asset-mount"
PROJECT_MOUNT="$LAB_ROOT/project-mount"
MANIFESTS="$LAB_ROOT/manifests"
ATTEMPTS="$LAB_ROOT/attempts.tsv"
COMPOSE_FILE="$LAB_ROOT/compose.yaml"
COMPOSE_PROJECT="fr06b1${suffix,,}"
ASSET_DOCKER_VOLUME="aionex-fr06b1-${suffix,,}-asset"
PROJECT_DOCKER_VOLUME="aionex-fr06b1-${suffix,,}-project"
ASSET_ACTIVE_KEY="$KEY_ROOT/asset-active.key"
ASSET_RECOVERY_KEY="$KEY_ROOT/asset-recovery.key"
PROJECT_ACTIVE_KEY="$KEY_ROOT/project-active.key"
PROJECT_RECOVERY_KEY="$KEY_ROOT/project-recovery.key"
WRONG_KEY="$KEY_ROOT/wrong.key"
ASSET_HEADER="$LAB_ROOT/asset-header.backup"
PROJECT_HEADER="$LAB_ROOT/project-header.backup"
ASSET_PROBE_MARKER="AIONEX_FR06B1_ASSET_PROBE_${suffix}"
PROJECT_PROBE_MARKER="AIONEX_FR06B1_PROJECT_PROBE_${suffix}"
mkdir -m 0700 "$ASSET_MOUNT" "$PROJECT_MOUNT" "$MANIFESTS"
: >"$ATTEMPTS"
SOURCE_MOUNTS=()

safe_compose_down() {
  set +e
  if [[ -f "$COMPOSE_FILE" && "$COMPOSE_PROJECT" == fr06b1* ]]; then
    FR06B_ASSET_VOLUME="$ASSET_DOCKER_VOLUME" \
      FR06B_PROJECT_VOLUME="$PROJECT_DOCKER_VOLUME" \
      docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" \
        down --remove-orphans >/dev/null 2>&1
  fi
  local container_id
  while read -r container_id; do
    [[ -n "$container_id" ]] && docker rm -f "$container_id" >/dev/null 2>&1
  done < <(docker ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" 2>/dev/null)
}

safe_cleanup() {
  set +e
  safe_compose_down
  for volume in "$ASSET_DOCKER_VOLUME" "$PROJECT_DOCKER_VOLUME"; do
    case "$volume" in aionex-fr06b1-*-asset|aionex-fr06b1-*-project)
      docker volume inspect "$volume" >/dev/null 2>&1 && docker volume rm -f "$volume" >/dev/null 2>&1
      ;;
    esac
  done
  mountpoint -q "$PROJECT_MOUNT" && umount "$PROJECT_MOUNT"
  mountpoint -q "$ASSET_MOUNT" && umount "$ASSET_MOUNT"
  local source_mount
  for ((index=${#SOURCE_MOUNTS[@]}-1; index>=0; index--)); do
    source_mount="${SOURCE_MOUNTS[$index]}"
    mountpoint -q "$source_mount" && umount "$source_mount"
  done
  for mapper in "$ASSET_WRONG_MAPPER" "$PROJECT_WRONG_MAPPER" "$PROJECT_MAPPER" "$ASSET_MAPPER"; do
    [[ -e "/dev/mapper/$mapper" ]] && cryptsetup close "$mapper"
  done
  case "$KEY_ROOT" in /dev/shm/aionex-fr06b1-keys.*) rm -rf -- "$KEY_ROOT" ;; esac
  case "$LAB_ROOT" in /var/tmp/aionex-fr06b1-lab.*) rm -rf -- "$LAB_ROOT" ;; esac
}
trap safe_cleanup EXIT

PRODUCTION_CONTAINERS_BEFORE="$(docker ps --no-trunc --format '{{.ID}} {{.Names}}' | LC_ALL=C sort | sha256sum | awk '{print $1}')"
DOCKER_ROOT="$(docker info --format '{{.DockerRootDir}}')"
[[ "$DOCKER_ROOT" == /* && -d "$DOCKER_ROOT/volumes" ]] || {
  echo "Docker root is unavailable" >&2
  exit 78
}

declare -A SOURCE_PATHS=()
install -d -m 0700 "$LAB_ROOT/sources"
for root in "${ALL_ROOTS[@]}"; do
  volume="web-dashboard_${root}"
  source_path="$(docker volume inspect --format '{{.Mountpoint}}' "$volume")"
  expected_path="$DOCKER_ROOT/volumes/$volume/_data"
  [[ "$source_path" == "$expected_path" ]] || {
    echo "unexpected Docker mountpoint for $volume" >&2
    exit 78
  }
  [[ -d "$source_path" && ! -L "$source_path" ]] || {
    echo "unsafe Docker volume root for $volume" >&2
    exit 78
  }
  source_mirror="$LAB_ROOT/sources/$root"
  install -d -m 0700 "$source_mirror"
  mount --bind "$source_path" "$source_mirror"
  mount -o remount,bind,ro,nodev,nosuid,noexec "$source_mirror"
  mirror_options=",$(findmnt -n -o OPTIONS --target "$source_mirror"),"
  [[ "$mirror_options" == *,ro,* && "$mirror_options" == *,nodev,* \
    && "$mirror_options" == *,nosuid,* && "$mirror_options" == *,noexec,* ]]
  SOURCE_MOUNTS+=("$source_mirror")
  SOURCE_PATHS["$root"]="$source_mirror"
done

for key in "$ASSET_ACTIVE_KEY" "$ASSET_RECOVERY_KEY" \
  "$PROJECT_ACTIVE_KEY" "$PROJECT_RECOVERY_KEY" "$WRONG_KEY"; do
  dd if=/dev/urandom of="$key" bs=64 count=1 status=none
  chmod 0600 "$key"
  [[ "$(stat -c '%F:%a:%h' "$key")" == "regular file:600:1" ]]
done

prepare_image() {
  local image="$1" active_key="$2" recovery_key="$3" label="$4" filesystem_label="$5"
  fallocate -l 256M "$image"
  [[ "$(stat -c '%F:%a:%h' "$image")" == "regular file:600:1" ]] || {
    echo "lab target must remain a private single-link regular file" >&2
    exit 78
  }
  local size allocated
  size="$(stat -c %s "$image")"
  allocated="$(( $(stat -c %b "$image") * 512 ))"
  [[ "$allocated" -ge "$size" ]] || { echo "lab image is sparse" >&2; exit 78; }
  cryptsetup luksFormat --type luks2 --cipher aes-xts-plain64 --key-size 512 \
    --pbkdf argon2id --batch-mode --key-file "$active_key" "$image"
  cryptsetup luksAddKey "$image" "$recovery_key" --key-file "$active_key"
  cryptsetup isLuks "$image"
  [[ "$(blkid -o value -s TYPE "$image")" == "crypto_LUKS" ]]
  cryptsetup open --type luks --key-file "$active_key" "$image" "$label"
  mkfs.ext4 -q -L "$filesystem_label" "/dev/mapper/$label"
}

prepare_image "$ASSET_IMAGE" "$ASSET_ACTIVE_KEY" "$ASSET_RECOVERY_KEY" \
  "$ASSET_MAPPER" AIONEX_FR06B_A
prepare_image "$PROJECT_IMAGE" "$PROJECT_ACTIVE_KEY" "$PROJECT_RECOVERY_KEY" \
  "$PROJECT_MAPPER" AIONEX_FR06B_P
cryptsetup luksHeaderBackup "$ASSET_IMAGE" --header-backup-file "$ASSET_HEADER"
cryptsetup luksHeaderBackup "$PROJECT_IMAGE" --header-backup-file "$PROJECT_HEADER"
for header in "$ASSET_HEADER" "$PROJECT_HEADER"; do
  header_mode="$(stat -c '%F:%a:%h' "$header")"
  [[ "$header_mode" == "regular file:400:1" || "$header_mode" == "regular file:600:1" ]]
done
ASSET_HEADER_BYTES="$(stat -c %s "$ASSET_HEADER")"
PROJECT_HEADER_BYTES="$(stat -c %s "$PROJECT_HEADER")"

mount -o nodev,nosuid,noexec "/dev/mapper/$ASSET_MAPPER" "$ASSET_MOUNT"
mount -o nodev,nosuid "/dev/mapper/$PROJECT_MAPPER" "$PROJECT_MOUNT"
ASSET_OPTIONS=",$(findmnt -n -o OPTIONS --target "$ASSET_MOUNT"),"
PROJECT_OPTIONS=",$(findmnt -n -o OPTIONS --target "$PROJECT_MOUNT"),"
[[ "$ASSET_OPTIONS" == *,nodev,* && "$ASSET_OPTIONS" == *,nosuid,* && "$ASSET_OPTIONS" == *,noexec,* ]]
[[ "$PROJECT_OPTIONS" == *,nodev,* && "$PROJECT_OPTIONS" == *,nosuid,* && "$PROJECT_OPTIONS" != *,noexec,* ]]

COPY_NANOSECONDS=0
copy_root() {
  local root="$1" target_root="$2"
  local source_root="${SOURCE_PATHS[$root]}"
  local attempt start end
  for attempt in 1 2 3; do
    rm -f -- "$MANIFESTS/$root.source-pre.json" \
      "$MANIFESTS/$root.source-post.json" "$MANIFESTS/$root.target.json"
    python3 "$HELPER" manifest --root "$source_root" \
      --output "$MANIFESTS/$root.source-pre.json"
    install -d -m 0700 "$target_root"
    start="$(date +%s%N)"
    rsync -aH --numeric-ids --delete --safe-links --no-specials --no-devices \
      "$source_root/" "$target_root/"
    end="$(date +%s%N)"
    COPY_NANOSECONDS="$((COPY_NANOSECONDS + end - start))"
    chown --reference="$source_root" "$target_root"
    chmod --reference="$source_root" "$target_root"
    python3 "$HELPER" manifest --root "$source_root" \
      --output "$MANIFESTS/$root.source-post.json"
    python3 "$HELPER" manifest --root "$target_root" \
      --output "$MANIFESTS/$root.target.json"
    if python3 "$HELPER" compare \
        --left "$MANIFESTS/$root.source-pre.json" \
        --right "$MANIFESTS/$root.source-post.json" >/dev/null 2>&1 \
      && python3 "$HELPER" compare \
        --left "$MANIFESTS/$root.source-post.json" \
        --right "$MANIFESTS/$root.target.json" >/dev/null 2>&1; then
      printf '%s\t%s\n' "$root" "$attempt" >>"$ATTEMPTS"
      return 0
    fi
  done
  echo "source did not remain stable for isolated copy: $root" >&2
  return 1
}

for root in "${PASSIVE_ROOTS[@]}"; do
  copy_root "$root" "$ASSET_MOUNT/$root"
done
copy_root "$PROJECT_ROOT" "$PROJECT_MOUNT/$PROJECT_ROOT"
sync -f "$ASSET_MOUNT"
sync -f "$PROJECT_MOUNT"

install -d -m 0700 "$ASSET_MOUNT/__fr06b_probe" "$PROJECT_MOUNT/__fr06b_probe"
printf '%s\n' "$ASSET_PROBE_MARKER" >"$ASSET_MOUNT/__fr06b_probe/marker"
printf '%s\n' "$PROJECT_PROBE_MARKER" >"$PROJECT_MOUNT/__fr06b_probe/marker"
cat >"$ASSET_MOUNT/__fr06b_probe/exec-probe.sh" <<EOF
#!/bin/sh
echo "$ASSET_PROBE_MARKER"
EOF
cat >"$PROJECT_MOUNT/__fr06b_probe/exec-probe.sh" <<EOF
#!/bin/sh
echo "$PROJECT_PROBE_MARKER"
EOF
chmod 0700 "$ASSET_MOUNT/__fr06b_probe/exec-probe.sh" \
  "$PROJECT_MOUNT/__fr06b_probe/exec-probe.sh"
sync -f "$ASSET_MOUNT"
sync -f "$PROJECT_MOUNT"
umount "$PROJECT_MOUNT"
umount "$ASSET_MOUNT"

docker volume create --driver local --opt type=ext4 \
  --opt "device=/dev/mapper/$ASSET_MAPPER" --opt "o=nodev,nosuid,noexec" \
  "$ASSET_DOCKER_VOLUME" >/dev/null
docker volume create --driver local --opt type=ext4 \
  --opt "device=/dev/mapper/$PROJECT_MAPPER" --opt "o=nodev,nosuid" \
  "$PROJECT_DOCKER_VOLUME" >/dev/null

cat >"$COMPOSE_FILE" <<'YAML'
services:
  asset-read:
    image: aionex-aios-backend:local
    pull_policy: never
    network_mode: none
    read_only: true
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    entrypoint: ["/bin/sh", "-ceu"]
    command: ["test -r /probe/marker"]
    volumes:
      - type: volume
        source: asset
        target: /probe
        read_only: true
        volume:
          subpath: __fr06b_probe
  asset-noexec:
    image: aionex-aios-backend:local
    pull_policy: never
    network_mode: none
    read_only: true
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    entrypoint: ["/probe/exec-probe.sh"]
    volumes:
      - type: volume
        source: asset
        target: /probe
        read_only: true
        volume:
          subpath: __fr06b_probe
  project-exec:
    image: aionex-aios-backend:local
    pull_policy: never
    network_mode: none
    read_only: true
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    entrypoint: ["/probe/exec-probe.sh"]
    volumes:
      - type: volume
        source: project
        target: /probe
        read_only: true
        volume:
          subpath: __fr06b_probe
volumes:
  asset:
    external: true
    name: ${FR06B_ASSET_VOLUME:?}
  project:
    external: true
    name: ${FR06B_PROJECT_VOLUME:?}
YAML

compose_run() {
  FR06B_ASSET_VOLUME="$ASSET_DOCKER_VOLUME" \
    FR06B_PROJECT_VOLUME="$PROJECT_DOCKER_VOLUME" \
    docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" "$@"
}

compose_run config --quiet
compose_run run --rm --no-deps --pull never asset-read >/dev/null
compose_run run --rm --no-deps --pull never project-exec >/dev/null
if compose_run run --rm --no-deps --pull never asset-noexec \
  >"$LAB_ROOT/asset-noexec.stdout" 2>"$LAB_ROOT/asset-noexec.stderr"; then
  echo "passive asset noexec mount unexpectedly executed a file" >&2
  exit 1
fi
safe_compose_down

for volume in "$ASSET_DOCKER_VOLUME" "$PROJECT_DOCKER_VOLUME"; do
  volume_mount="$(docker volume inspect --format '{{.Mountpoint}}' "$volume")"
  if mountpoint -q "$volume_mount"; then
    echo "temporary Docker volume remained mounted" >&2
    exit 1
  fi
done

cryptsetup close "$PROJECT_MAPPER"
cryptsetup close "$ASSET_MAPPER"
[[ ! -e "/dev/mapper/$ASSET_MAPPER" && ! -e "/dev/mapper/$PROJECT_MAPPER" ]]
if LC_ALL=C grep -aF -m1 "$ASSET_PROBE_MARKER" "$ASSET_IMAGE" >/dev/null; then
  echo "plaintext asset marker found in closed LUKS image" >&2
  exit 1
fi
if LC_ALL=C grep -aF -m1 "$PROJECT_PROBE_MARKER" "$PROJECT_IMAGE" >/dev/null; then
  echo "plaintext project marker found in closed LUKS image" >&2
  exit 1
fi
if cryptsetup open --type luks --key-file "$WRONG_KEY" "$ASSET_IMAGE" \
  "$ASSET_WRONG_MAPPER" 2>/dev/null; then
  cryptsetup close "$ASSET_WRONG_MAPPER"
  echo "wrong key unexpectedly opened asset vault" >&2
  exit 1
fi
if cryptsetup open --type luks --key-file "$WRONG_KEY" "$PROJECT_IMAGE" \
  "$PROJECT_WRONG_MAPPER" 2>/dev/null; then
  cryptsetup close "$PROJECT_WRONG_MAPPER"
  echo "wrong key unexpectedly opened project vault" >&2
  exit 1
fi

if compose_run run --rm --no-deps --pull never asset-read \
  >"$LAB_ROOT/missing-mapper.stdout" 2>"$LAB_ROOT/missing-mapper.stderr"; then
  echo "missing mapper unexpectedly started against a fallback directory" >&2
  exit 1
fi
safe_compose_down

for volume in "$ASSET_DOCKER_VOLUME" "$PROJECT_DOCKER_VOLUME"; do
  volume_mount="$(docker volume inspect --format '{{.Mountpoint}}' "$volume")"
  [[ ! -L "$volume_mount" ]]
  [[ -d "$volume_mount" ]]
  [[ -z "$(find "$volume_mount" -mindepth 1 -maxdepth 1 -print -quit)" ]]
  docker volume rm "$volume" >/dev/null
done

cryptsetup open --type luks --key-file "$ASSET_RECOVERY_KEY" \
  "$ASSET_IMAGE" "$ASSET_MAPPER"
cryptsetup open --type luks --key-file "$PROJECT_RECOVERY_KEY" \
  "$PROJECT_IMAGE" "$PROJECT_MAPPER"
mount -o ro,nodev,nosuid,noexec "/dev/mapper/$ASSET_MAPPER" "$ASSET_MOUNT"
mount -o ro,nodev,nosuid "/dev/mapper/$PROJECT_MAPPER" "$PROJECT_MOUNT"
for root in "${PASSIVE_ROOTS[@]}"; do
  python3 "$HELPER" manifest --root "$ASSET_MOUNT/$root" \
    --output "$MANIFESTS/$root.recovery.json"
  python3 "$HELPER" compare --left "$MANIFESTS/$root.source-post.json" \
    --right "$MANIFESTS/$root.recovery.json"
done
python3 "$HELPER" manifest --root "$PROJECT_MOUNT/$PROJECT_ROOT" \
  --output "$MANIFESTS/$PROJECT_ROOT.recovery.json"
python3 "$HELPER" compare --left "$MANIFESTS/$PROJECT_ROOT.source-post.json" \
  --right "$MANIFESTS/$PROJECT_ROOT.recovery.json"
umount "$PROJECT_MOUNT"
umount "$ASSET_MOUNT"
cryptsetup close "$PROJECT_MAPPER"
cryptsetup close "$ASSET_MAPPER"

SUMMARY_JSON="$(python3 "$HELPER" summary --manifests "$MANIFESTS" \
  --attempts "$ATTEMPTS" --copy-nanoseconds "$COPY_NANOSECONDS" \
  --asset-header-bytes "$ASSET_HEADER_BYTES" \
  --project-header-bytes "$PROJECT_HEADER_BYTES")"
SOURCE_COMMIT="$(git -C "$SCRIPT_ROOT" rev-parse HEAD)"
OBSERVED_AT="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

safe_cleanup
trap - EXIT
[[ ! -e "/dev/mapper/$ASSET_MAPPER" && ! -e "/dev/mapper/$PROJECT_MAPPER" ]]
[[ ! -e "$KEY_ROOT" && ! -e "$LAB_ROOT" ]]
! docker volume inspect "$ASSET_DOCKER_VOLUME" >/dev/null 2>&1
! docker volume inspect "$PROJECT_DOCKER_VOLUME" >/dev/null 2>&1
PRODUCTION_CONTAINERS_AFTER="$(docker ps --no-trunc --format '{{.ID}} {{.Names}}' | LC_ALL=C sort | sha256sum | awk '{print $1}')"
[[ "$PRODUCTION_CONTAINERS_AFTER" == "$PRODUCTION_CONTAINERS_BEFORE" ]] || {
  echo "production container identity changed during the isolated lab" >&2
  exit 1
}

python3 "$HELPER" receipt --output "$RECEIPT" --observed-at "$OBSERVED_AT" \
  --source-commit "$SOURCE_COMMIT" --summary-json "$SUMMARY_JSON"
