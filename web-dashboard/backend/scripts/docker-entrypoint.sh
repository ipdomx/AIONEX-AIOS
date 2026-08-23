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

    three_d_secret_source="${THREE_D_RUNPOD_SECRET_FILE:-}"
    if [ -n "$three_d_secret_source" ] && [ -f "$three_d_secret_source" ]; then
        runtime_dir=/run/aionex
        three_d_secret_runtime="$runtime_dir/runpod-gpu.env"
        install -d -m 0700 -o aionex -g aionex "$runtime_dir"
        if [ "$three_d_secret_source" != "$three_d_secret_runtime" ]; then
            install -m 0400 -o aionex -g aionex "$three_d_secret_source" "$three_d_secret_runtime"
        else
            chown aionex:aionex "$three_d_secret_runtime"
            chmod 0400 "$three_d_secret_runtime"
        fi
        export THREE_D_RUNPOD_SECRET_FILE="$three_d_secret_runtime"
    fi

    audio_song_secret_source="${AUDIO_SONG_RUNPOD_SECRET_FILE:-}"
    if [ -n "$audio_song_secret_source" ] && [ -f "$audio_song_secret_source" ]; then
        runtime_dir=/run/aionex
        audio_song_secret_runtime="$runtime_dir/runpod-open-song.env"
        install -d -m 0700 -o aionex -g aionex "$runtime_dir"
        if [ "$audio_song_secret_source" != "$audio_song_secret_runtime" ]; then
            install -m 0400 -o aionex -g aionex "$audio_song_secret_source" "$audio_song_secret_runtime"
        else
            chown aionex:aionex "$audio_song_secret_runtime"
            chmod 0400 "$audio_song_secret_runtime"
        fi
        export AUDIO_SONG_RUNPOD_SECRET_FILE="$audio_song_secret_runtime"
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

    project_npm_cache="${PROJECT_EXECUTION_NPM_CACHE:-}"
    if [ -n "$project_npm_cache" ]; then
        install -d -m 0700 -o aionex -g aionex "$project_npm_cache"
    fi

    portal_asset_root="${PORTAL_ASSET_ROOT-/var/lib/aionex/portal-assets}"
    if [ -n "$portal_asset_root" ]; then
        install -d -m 0750 -o aionex -g aionex "$portal_asset_root"
    fi

    studio_asset_root="${STUDIO_ASSET_ROOT-/var/lib/aionex/studio-assets}"
    if [ -n "$studio_asset_root" ]; then
        install -d -m 0700 -o aionex -g aionex "$studio_asset_root"
    fi

    media_storage_root="${MEDIA_STORAGE_ROOT-/var/lib/aionex/media-assets}"
    if [ -n "$media_storage_root" ]; then
        install -d -m 0700 -o aionex -g aionex "$media_storage_root"
    fi

    mobile_release_root="${MOBILE_RELEASE_ROOT-/var/lib/aionex/mobile-releases}"
    if [ -n "$mobile_release_root" ]; then
        # Readers mount the release store read-only. Preparing ownership is only
        # required when the path is writable; an existing readable read-only
        # mount is already valid and must not prevent the API from starting.
        if ! install -d -m 0750 -o aionex -g aionex "$mobile_release_root" 2>/dev/null; then
            if [ ! -d "$mobile_release_root" ] || [ ! -r "$mobile_release_root" ]; then
                echo "Unable to prepare mobile release root: $mobile_release_root" >&2
                exit 1
            fi
        fi
    fi

    security_remediation_root="${SECURITY_REMEDIATION_ROOT:-}"
    if [ -n "$security_remediation_root" ]; then
        install -d -m 0700 -o aionex -g aionex "$security_remediation_root"
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

    user_telegram_token_source="${AIOS_USER_TELEGRAM_BOT_TOKEN_FILE:-}"
    if [ -n "$user_telegram_token_source" ] && [ -f "$user_telegram_token_source" ]; then
        runtime_dir=/run/aionex
        user_telegram_token_runtime="$runtime_dir/user-telegram-bot-token"
        install -d -m 0700 -o aionex -g aionex "$runtime_dir"
        if [ "$user_telegram_token_source" != "$user_telegram_token_runtime" ]; then
            install -m 0400 -o aionex -g aionex "$user_telegram_token_source" "$user_telegram_token_runtime"
        else
            chown aionex:aionex "$user_telegram_token_runtime"
            chmod 0400 "$user_telegram_token_runtime"
        fi
        export AIOS_USER_TELEGRAM_BOT_TOKEN_FILE="$user_telegram_token_runtime"
    fi

    exec su-exec aionex "$@"
fi

exec "$@"
