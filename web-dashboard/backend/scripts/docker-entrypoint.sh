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
    project_secret_source="${PROJECT_EXECUTION_SECRET_FILE:-}"
    if [ -n "$project_secret_source" ] && [ -f "$project_secret_source" ]; then
        runtime_dir=/run/aionex
        project_secret_runtime="$runtime_dir/project-openai.env"
        install -d -m 0700 -o aionex -g aionex "$runtime_dir"
        if [ "$project_secret_source" != "$project_secret_runtime" ]; then
            install -m 0400 -o aionex -g aionex "$project_secret_source" "$project_secret_runtime"
        else
            chown aionex:aionex "$project_secret_runtime"
            chmod 0400 "$project_secret_runtime"
        fi
        export PROJECT_EXECUTION_SECRET_FILE="$project_secret_runtime"
    fi

    project_reference_source="${PROJECT_EXECUTION_LOCAL_REFERENCE:-}"
    if [ -n "$project_reference_source" ] && [ -d "$project_reference_source" ]; then
        runtime_dir=/run/aionex
        project_reference_runtime="$runtime_dir/phase22b-local-reference"
        install -d -m 0700 -o aionex -g aionex "$runtime_dir"
        rm -rf "$project_reference_runtime"
        cp -a "$project_reference_source" "$project_reference_runtime"
        chown -R aionex:aionex "$project_reference_runtime"
        chmod -R u=rwX,go= "$project_reference_runtime"
        export PROJECT_EXECUTION_LOCAL_REFERENCE="$project_reference_runtime"
    fi

    project_output_root="${PROJECT_EXECUTION_OUTPUT_ROOT:-}"
    if [ -n "$project_output_root" ]; then
        install -d -m 0700 -o aionex -g aionex "$project_output_root"
    fi

    portal_asset_root="${PORTAL_ASSET_ROOT:-/var/lib/aionex/portal-assets}"
    if [ -n "$portal_asset_root" ]; then
        install -d -m 0750 -o aionex -g aionex "$portal_asset_root"
    fi

    studio_asset_root="${STUDIO_ASSET_ROOT:-/var/lib/aionex/studio-assets}"
    if [ -n "$studio_asset_root" ]; then
        install -d -m 0700 -o aionex -g aionex "$studio_asset_root"
    fi

    mobile_release_root="${MOBILE_RELEASE_ROOT:-/var/lib/aionex/mobile-releases}"
    if [ -n "$mobile_release_root" ]; then
        install -d -m 0750 -o aionex -g aionex "$mobile_release_root"
    fi


    telegram_token_source="${AIOS_TELEGRAM_BOT_TOKEN_FILE:-}"
    if [ -n "$telegram_token_source" ] && [ -f "$telegram_token_source" ]; then
        runtime_dir=/run/aionex
        telegram_token_runtime="$runtime_dir/telegram-bot-token"
        install -d -m 0700 -o aionex -g aionex "$runtime_dir"
        if [ "$telegram_token_source" != "$telegram_token_runtime" ]; then
            install -m 0400 -o aionex -g aionex "$telegram_token_source" "$telegram_token_runtime"
        else
            chown aionex:aionex "$telegram_token_runtime"
            chmod 0400 "$telegram_token_runtime"
        fi
        export AIOS_TELEGRAM_BOT_TOKEN_FILE="$telegram_token_runtime"
    fi

    exec gosu aionex "$@"
fi

exec "$@"
