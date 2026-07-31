#!/bin/sh
set -eu

# Compose bind-mounts operator-managed credentials read-only.  The source file
# may legitimately be root:root mode 0600 on the host, so copy it into a private
# runtime path before dropping privileges.  No credential contents are logged.
if [ "$(id -u)" = "0" ]; then
    source_path="${FIREBASE_ADMIN_CREDENTIALS_JSON:-}"
    if [ -n "$source_path" ] && [ -f "$source_path" ]; then
        runtime_dir=/run/aionex
        runtime_path="$runtime_dir/firebase-admin.json"
        install -d -m 0700 -o aionex -g aionex "$runtime_dir"
        if [ "$source_path" != "$runtime_path" ]; then
            install -m 0400 -o aionex -g aionex "$source_path" "$runtime_path"
        else
            chown aionex:aionex "$runtime_path"
            chmod 0400 "$runtime_path"
        fi
        export FIREBASE_ADMIN_CREDENTIALS_JSON="$runtime_path"
    fi
    exec gosu aionex "$@"
fi

exec "$@"
