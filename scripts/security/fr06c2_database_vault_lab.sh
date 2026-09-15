#!/usr/bin/env bash
set -euo pipefail

# FR-06C2 synthetic-only PostgreSQL/LUKS migration rehearsal.
# It must never mount or read production PGDATA or a production Docker volume.
ROOT="${FR06C2_LAB_ROOT:-/var/tmp}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-${RANDOM}"
LAB="${ROOT}/fr06c2-db-lab-${STAMP}"
KEYDIR="/dev/shm/fr06c2-db-lab-${STAMP}"
IMG="${LAB}/database-vault.luks2"
MNT="${LAB}/mnt"
SRC="${LAB}/plain-pgdata"
MAPPER="fr06c2-db-lab-${RANDOM}"
SOURCE_CONTAINER="fr06c2-src-${RANDOM}"
TARGET_CONTAINER="fr06c2-dst-${RANDOM}"
IMAGE="${FR06C2_POSTGRES_IMAGE:-aionex-aios-postgres:16-hardened}"

if [[ ${EUID} -ne 0 ]]; then
  echo '{"status":"blocked","reason":"root_required"}'
  exit 2
fi
for command in docker cryptsetup fallocate mkfs.ext4 mount umount rsync python3; do
  command -v "$command" >/dev/null || { echo "required command missing: $command" >&2; exit 2; }
done
case "$LAB" in
  /var/tmp/fr06c2-db-lab-*|/tmp/fr06c2-db-lab-*) ;;
  *) echo '{"status":"blocked","reason":"unsafe_lab_root"}'; exit 2;;
esac
if [[ "$SRC" == /var/lib/docker/* || "$MNT" == /var/lib/docker/* ]]; then
  echo '{"status":"blocked","reason":"production_path_forbidden"}'
  exit 2
fi
mkdir -p "$LAB" "$KEYDIR" "$MNT" "$SRC"
chmod 0700 "$LAB" "$KEYDIR" "$MNT" "$SRC"

cleanup() {
  docker rm -f "$SOURCE_CONTAINER" "$TARGET_CONTAINER" >/dev/null 2>&1 || true
  mountpoint -q "$MNT" && umount "$MNT" || true
  [[ -e "/dev/mapper/$MAPPER" ]] && cryptsetup close "$MAPPER" || true
  rm -rf "$KEYDIR" "$LAB"
}
trap cleanup EXIT

head -c 64 /dev/urandom >"$KEYDIR/active"
head -c 64 /dev/urandom >"$KEYDIR/recovery"
head -c 64 /dev/urandom >"$KEYDIR/wrong"
chmod 0600 "$KEYDIR"/*
fallocate -l 512M "$IMG"
cryptsetup luksFormat --batch-mode --type luks2 --cipher aes-xts-plain64 --key-size 512 --pbkdf argon2id --key-file "$KEYDIR/active" "$IMG"
cryptsetup luksAddKey --key-file "$KEYDIR/active" --new-keyfile "$KEYDIR/recovery" "$IMG"
cryptsetup open --type luks --key-file "$KEYDIR/active" "$IMG" "$MAPPER"
mkfs.ext4 -q -L AIONEX_DB_LAB "/dev/mapper/$MAPPER"
mount -o nodev,nosuid,noexec "/dev/mapper/$MAPPER" "$MNT"
chown 70:70 "$SRC" "$MNT"
chmod 0700 "$SRC" "$MNT"
PASSWORD="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(18))
PY
)"

docker run -d --name "$SOURCE_CONTAINER" --security-opt no-new-privileges:true --cap-drop ALL \
  -e POSTGRES_USER=labowner -e POSTGRES_PASSWORD="$PASSWORD" -e POSTGRES_DB=labdb \
  -v "$SRC:/var/lib/postgresql/data" "$IMAGE" >/dev/null
ready=0
for _ in $(seq 1 60); do
  if docker exec "$SOURCE_CONTAINER" psql -U labowner -d labdb -At -c 'select 1' 2>/dev/null | grep -qx 1; then ready=1; break; fi
  sleep 1
done
[[ "$ready" == 1 ]]
docker exec "$SOURCE_CONTAINER" psql -U labowner -d labdb -v ON_ERROR_STOP=1 \
  -c "CREATE TABLE fr06c_probe(id integer primary key, marker text not null); INSERT INTO fr06c_probe VALUES (1,'synthetic-db-vault-marker'),(2,'offline-copy-only'); CHECKPOINT;" >/dev/null
docker stop -t 60 "$SOURCE_CONTAINER" >/dev/null
docker rm "$SOURCE_CONTAINER" >/dev/null

manifest() {
  python3 - "$1" "$2" <<'PY'
import hashlib, json, os, stat, sys
root, output = sys.argv[1:]
rows=[]
for directory, dirs, files in os.walk(root, followlinks=False):
    dirs.sort()
    for name in sorted(files):
        path=os.path.join(directory,name)
        info=os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SystemExit("unsafe file in PostgreSQL manifest")
        digest=hashlib.sha256()
        with open(path,"rb",buffering=0) as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b""):
                digest.update(chunk)
        rows.append([os.path.relpath(path,root),info.st_size,stat.S_IMODE(info.st_mode),info.st_uid,info.st_gid,digest.hexdigest()])
rows.sort(key=lambda item:item[0])
with open(output,"w",encoding="utf-8") as stream:
    json.dump(rows,stream,separators=(",",":"))
print(len(rows))
PY
}
source_files="$(manifest "$SRC" "$LAB/source.json")"
start_ns="$(date +%s%N)"
rsync -aH --numeric-ids --delete --safe-links --no-devices --no-specials "$SRC/" "$MNT/"
end_ns="$(date +%s%N)"
sync -f "$MNT"
manifest "$MNT" "$LAB/target.json" >/dev/null
cmp -s "$LAB/source.json" "$LAB/target.json"

start_target() {
  docker run -d --name "$TARGET_CONTAINER" --security-opt no-new-privileges:true --cap-drop ALL \
    -e POSTGRES_USER=labowner -e POSTGRES_PASSWORD="$PASSWORD" -e POSTGRES_DB=labdb \
    -v "$MNT:/var/lib/postgresql/data" "$IMAGE" >/dev/null
  local ready=0
  for _ in $(seq 1 60); do
    if docker exec "$TARGET_CONTAINER" psql -U labowner -d labdb -At -c 'select 1' 2>/dev/null | grep -qx 1; then ready=1; break; fi
    sleep 1
  done
  [[ "$ready" == 1 ]]
  docker exec "$TARGET_CONTAINER" psql -U labowner -d labdb -At \
    -c "SELECT count(*),string_agg(marker,',' ORDER BY id) FROM fr06c_probe;"
}

rows="$(start_target)"
[[ "$rows" == "2|synthetic-db-vault-marker,offline-copy-only" ]]
docker stop -t 60 "$TARGET_CONTAINER" >/dev/null
docker rm "$TARGET_CONTAINER" >/dev/null
umount "$MNT"
cryptsetup close "$MAPPER"
if cryptsetup open --type luks --key-file "$KEYDIR/wrong" "$IMG" "$MAPPER" >/dev/null 2>&1; then
  echo '{"status":"failed","reason":"wrong_key_accepted"}'
  exit 2
fi
cryptsetup open --type luks --key-file "$KEYDIR/recovery" "$IMG" "$MAPPER"
mount -o nodev,nosuid,noexec "/dev/mapper/$MAPPER" "$MNT"
rows_recovery="$(start_target)"
[[ "$rows_recovery" == "$rows" ]]
wal_bytes="$(du -sb "$MNT/pg_wal" | awk '{print $1}')"
payload_bytes="$(du -sb "$MNT" | awk '{print $1}')"
copy_ms="$(( (end_ns-start_ns)/1000000 ))"
python3 - "$source_files" "$wal_bytes" "$payload_bytes" "$copy_ms" <<'PY'
import json,sys
print(json.dumps({
  "all_checks_passed": True,
  "synthetic_only": True,
  "source_file_count": int(sys.argv[1]),
  "luks2": True,
  "active_key_open": True,
  "wrong_key_rejected": True,
  "recovery_key_reopen": True,
  "offline_source_required": True,
  "manifest_match": True,
  "postgres_start_on_encrypted_noexec_mount": True,
  "synthetic_rows_verified": 2,
  "pg_wal_bytes": int(sys.argv[2]),
  "payload_bytes": int(sys.argv[3]),
  "final_copy_ms": int(sys.argv[4]),
  "production_data_touched": False,
  "production_services_touched": False,
},sort_keys=True))
PY
