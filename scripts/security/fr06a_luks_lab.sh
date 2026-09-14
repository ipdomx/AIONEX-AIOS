#!/usr/bin/env bash
# FR-06A isolated LUKS2 lifecycle and performance laboratory.
# It operates only on a newly created regular file under /var/tmp and ephemeral
# keys under /dev/shm. It never targets a live block device or production mount.
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
[[ "$EUID" -eq 0 ]] || { echo "FR-06A lab requires root" >&2; exit 77; }

for command in cryptsetup mkfs.ext4 mount umount mountpoint fallocate dd grep sha256sum python3 date findmnt git; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 69; }
done
[[ "$(findmnt -n -o FSTYPE --target /dev/shm)" == "tmpfs" ]] || {
  echo "/dev/shm must be tmpfs so lab keys are not persisted" >&2
  exit 78
}

LAB_ROOT="$(mktemp -d /var/tmp/aionex-fr06a-lab.XXXXXX)"
KEY_ROOT="$(mktemp -d /dev/shm/aionex-fr06a-keys.XXXXXX)"
case "$LAB_ROOT" in /var/tmp/aionex-fr06a-lab.*) ;; *) exit 78 ;; esac
case "$KEY_ROOT" in /dev/shm/aionex-fr06a-keys.*) ;; *) exit 78 ;; esac

suffix="${LAB_ROOT##*.}"
suffix="${suffix//[^a-zA-Z0-9]/}"
MAPPER="aionex-fr06a-${suffix}"
WRONG_MAPPER="${MAPPER}-wrong"
IMAGE="$LAB_ROOT/vault.luks2"
MOUNT_DIR="$LAB_ROOT/mnt"
PLAIN_FILE="$LAB_ROOT/plain-benchmark.bin"
HEADER_BACKUP="$LAB_ROOT/luks-header.backup"
ACTIVE_KEY="$KEY_ROOT/active.key"
RECOVERY_KEY="$KEY_ROOT/recovery.key"
WRONG_KEY="$KEY_ROOT/wrong.key"
mkdir -m 0700 "$MOUNT_DIR"

safe_cleanup() {
  set +e
  mountpoint -q "$MOUNT_DIR" && umount "$MOUNT_DIR"
  [[ -e "/dev/mapper/$WRONG_MAPPER" ]] && cryptsetup close "$WRONG_MAPPER"
  [[ -e "/dev/mapper/$MAPPER" ]] && cryptsetup close "$MAPPER"
  case "$KEY_ROOT" in /dev/shm/aionex-fr06a-keys.*) rm -rf -- "$KEY_ROOT" ;; esac
  case "$LAB_ROOT" in /var/tmp/aionex-fr06a-lab.*) rm -rf -- "$LAB_ROOT" ;; esac
}
trap safe_cleanup EXIT

dd if=/dev/urandom of="$ACTIVE_KEY" bs=64 count=1 status=none
dd if=/dev/urandom of="$RECOVERY_KEY" bs=64 count=1 status=none
dd if=/dev/urandom of="$WRONG_KEY" bs=64 count=1 status=none
chmod 0600 "$ACTIVE_KEY" "$RECOVERY_KEY" "$WRONG_KEY"
[[ "$(stat -c '%F:%a:%h' "$ACTIVE_KEY")" == "regular file:600:1" ]]

fallocate -l 384M "$IMAGE"
[[ "$(stat -c '%F:%a:%h' "$IMAGE")" == "regular file:600:1" ]] || {
  echo "lab target must remain a private single-link regular file" >&2
  exit 78
}

cryptsetup luksFormat   --type luks2   --cipher aes-xts-plain64   --key-size 512   --pbkdf argon2id   --batch-mode   --key-file "$ACTIVE_KEY"   "$IMAGE"
cryptsetup luksAddKey "$IMAGE" "$RECOVERY_KEY" --key-file "$ACTIVE_KEY"
cryptsetup isLuks "$IMAGE"
[[ "$(blkid -o value -s TYPE "$IMAGE")" == "crypto_LUKS" ]]

cryptsetup open --type luks --key-file "$ACTIVE_KEY" "$IMAGE" "$MAPPER"
mkfs.ext4 -q -L AIONEX_FR06A_LAB "/dev/mapper/$MAPPER"
mount -o nodev,nosuid,noexec "/dev/mapper/$MAPPER" "$MOUNT_DIR"

MARKER="AIONEX_FR06A_PLAINTEXT_PROBE_${suffix}"
python3 - "$MOUNT_DIR/probe.txt" "$MARKER" <<'PY'
import os
import sys
path, marker = sys.argv[1:]
with open(path, "x", encoding="utf-8") as stream:
    stream.write(marker + "\n")
    stream.flush()
    os.fsync(stream.fileno())
PY
PROBE_SHA256="$(sha256sum "$MOUNT_DIR/probe.txt" | awk '{print $1}')"

measure_write() {
  local target="$1"
  local start end
  start="$(date +%s%N)"
  dd if=/dev/zero of="$target" bs=4M count=32 oflag=direct conv=fsync status=none
  end="$(date +%s%N)"
  python3 - "$start" "$end" <<'PY'
import sys
start, end = map(int, sys.argv[1:])
seconds = (end - start) / 1_000_000_000
print(f"{128 / seconds:.3f}")
PY
}

PLAIN_WRITE_MIB_S="$(measure_write "$PLAIN_FILE")"
rm -f -- "$PLAIN_FILE"

ENCRYPTED_FILE="$MOUNT_DIR/encrypted-benchmark.bin"
ENCRYPTED_WRITE_MIB_S="$(measure_write "$ENCRYPTED_FILE")"
rm -f -- "$ENCRYPTED_FILE"

umount "$MOUNT_DIR"
cryptsetup close "$MAPPER"
[[ ! -e "/dev/mapper/$MAPPER" ]]
cryptsetup isLuks "$IMAGE"

if LC_ALL=C grep -aF -m1 "$MARKER" "$IMAGE" >/dev/null; then
  echo "plaintext marker found in closed LUKS image" >&2
  exit 1
fi

if cryptsetup open --type luks --key-file "$WRONG_KEY" "$IMAGE" "$WRONG_MAPPER" 2>/dev/null; then
  cryptsetup close "$WRONG_MAPPER"
  echo "wrong key unexpectedly opened LUKS image" >&2
  exit 1
fi
[[ ! -e "/dev/mapper/$WRONG_MAPPER" ]]

cryptsetup luksHeaderBackup "$IMAGE" --header-backup-file "$HEADER_BACKUP"
HEADER_MODE="$(stat -c '%F:%a:%h' "$HEADER_BACKUP")"
[[ "$HEADER_MODE" == "regular file:400:1" || "$HEADER_MODE" == "regular file:600:1" ]]
HEADER_BACKUP_BYTES="$(stat -c %s "$HEADER_BACKUP")"

# Destructive recovery rehearsal is restricted to the validated temporary image.
[[ "$IMAGE" == /var/tmp/aionex-fr06a-lab.*/vault.luks2 ]]
[[ "$(stat -c '%F:%a:%h' "$IMAGE")" == "regular file:600:1" ]]
cryptsetup luksErase --batch-mode "$IMAGE"
if cryptsetup open --type luks --key-file "$ACTIVE_KEY" "$IMAGE" "$MAPPER" 2>/dev/null; then
  cryptsetup close "$MAPPER"
  echo "erased keyslots unexpectedly remained usable" >&2
  exit 1
fi
cryptsetup luksHeaderRestore --batch-mode "$IMAGE" --header-backup-file "$HEADER_BACKUP"

cryptsetup open --type luks --key-file "$RECOVERY_KEY" "$IMAGE" "$MAPPER"
mount -o ro,nodev,nosuid,noexec "/dev/mapper/$MAPPER" "$MOUNT_DIR"
[[ "$(sha256sum "$MOUNT_DIR/probe.txt" | awk '{print $1}')" == "$PROBE_SHA256" ]]
umount "$MOUNT_DIR"
cryptsetup close "$MAPPER"
[[ ! -e "/dev/mapper/$MAPPER" ]]

SOURCE_COMMIT="$(git -C "$(dirname "$0")/../.." rev-parse HEAD)"
OBSERVED_AT="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
WRITE_RATIO="$(python3 - "$PLAIN_WRITE_MIB_S" "$ENCRYPTED_WRITE_MIB_S" <<'PY'
import sys
plain, encrypted = map(float, sys.argv[1:])
print(f"{encrypted / plain:.4f}")
PY
)"

safe_cleanup
trap - EXIT
[[ ! -e "/dev/mapper/$MAPPER" ]]
[[ ! -e "$KEY_ROOT" ]]
[[ ! -e "$LAB_ROOT" ]]

python3 - "$RECEIPT" "$OBSERVED_AT" "$SOURCE_COMMIT" "$PLAIN_WRITE_MIB_S" "$ENCRYPTED_WRITE_MIB_S" "$WRITE_RATIO" "$HEADER_BACKUP_BYTES" <<'PY'
import json
import os
import sys
from pathlib import Path

(
    receipt,
    observed_at,
    source_commit,
    plain_write,
    encrypted_write,
    write_ratio,
    header_backup_bytes,
) = sys.argv[1:]
payload = {
    "schema_version": 1,
    "observed_at": observed_at,
    "source_commit": source_commit,
    "lab": {
        "type": "file_backed_luks2_isolated_rehearsal",
        "backing_file_bytes": 384 * 1024 * 1024,
        "benchmark_payload_bytes": 128 * 1024 * 1024,
        "cipher": "aes-xts-plain64",
        "key_bits": 512,
        "pbkdf": "argon2id",
        "filesystem": "ext4",
        "mount_options": ["nodev", "nosuid", "noexec"],
        "keys_created_only_on_tmpfs": True,
        "key_material_persisted": False,
    },
    "checks": {
        "luks2_format_verified": True,
        "active_key_open_verified": True,
        "secondary_recovery_key_open_verified": True,
        "wrong_key_rejected": True,
        "closed_raw_plaintext_marker_absent": True,
        "closed_mapper_absent": True,
        "header_backup_created_private": True,
        "header_backup_bytes": int(header_backup_bytes),
        "erased_keyslots_rejected": True,
        "header_restore_verified": True,
        "payload_checksum_after_header_restore_verified": True,
        "cleanup_verified": True,
        "live_block_devices_formatted": False,
        "production_mounts_changed": False,
        "production_services_touched": False,
        "reboot_performed": False,
    },
    "performance": {
        "method": "128 MiB sequential direct write I/O on the same ext4 host filesystem",
        "plain_write_mib_s": float(plain_write),
        "encrypted_write_mib_s": float(encrypted_write),
        "encrypted_to_plain_write_ratio": float(write_ratio),
        "read_comparison_recorded": False,
        "note": "Read comparison is intentionally omitted because loopback cache layers make it misleading. This write result is a feasibility signal, not a production SLO.",
    },
    "all_checks_passed": True,
}
path = Path(receipt)
path.parent.mkdir(parents=True, exist_ok=True)
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
fd = os.open(path, flags, 0o644)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
print(json.dumps({"receipt": str(path), "all_checks_passed": True}, separators=(",", ":")))
PY
