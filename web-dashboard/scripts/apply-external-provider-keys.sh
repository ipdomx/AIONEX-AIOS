#!/usr/bin/env bash
set -euo pipefail

ROOT="/opt/AIOS/web-dashboard"
SOURCE="$ROOT/secrets/EXTERNAL_PROVIDER_KEYS.env"
TARGET="$ROOT/.env.production"

if [[ ! -f "$SOURCE" ]]; then
  echo "Missing $SOURCE" >&2
  exit 1
fi
chmod 0600 "$SOURCE"

python3 - "$SOURCE" "$TARGET" <<'PY'
from pathlib import Path
import sys
source=Path(sys.argv[1]); target=Path(sys.argv[2])
updates={}
for raw in source.read_text(encoding='utf-8').splitlines():
    line=raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k,v=line.split('=',1)
    k=k.strip(); v=v.strip()
    if v:
        updates[k]=v
lines=target.read_text(encoding='utf-8').splitlines() if target.exists() else []
out=[]; seen=set()
for raw in lines:
    if '=' in raw and not raw.lstrip().startswith('#'):
        k=raw.split('=',1)[0].strip()
        if k in updates:
            out.append(f"{k}={updates[k]}"); seen.add(k); continue
    out.append(raw)
for k,v in updates.items():
    if k not in seen:
        out.append(f"{k}={v}")
target.write_text('\n'.join(out).rstrip()+"\n", encoding='utf-8')
PY
chmod 0600 "$TARGET"

# Telegram worker consumes a mounted token file rather than the env directly.
telegram_token="$(grep '^AIOS_TELEGRAM_BOT_TOKEN=' "$SOURCE" | tail -1 | cut -d= -f2- || true)"
if [[ -n "$telegram_token" ]]; then
  token_file="/root/.config/aionex/telegram/bot-token"
  install -d -m 0700 "$(dirname "$token_file")"
  printf '%s' "$telegram_token" > "$token_file"
  chmod 0600 "$token_file"
  if ! grep -q '^AIOS_TELEGRAM_BOT_TOKEN_HOST_FILE=' "$TARGET"; then
    printf '\nAIOS_TELEGRAM_BOT_TOKEN_HOST_FILE=%s\n' "$token_file" >> "$TARGET"
  else
    sed -i "s#^AIOS_TELEGRAM_BOT_TOKEN_HOST_FILE=.*#AIOS_TELEGRAM_BOT_TOKEN_HOST_FILE=$token_file#" "$TARGET"
  fi
fi

echo "External provider keys applied. Empty entries were ignored."
