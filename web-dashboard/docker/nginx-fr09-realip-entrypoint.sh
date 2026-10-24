#!/bin/sh
# Optional, fail-closed Nginx real-IP configuration for a Cloudflare Tunnel.
# Keep the immutable, previously attested /etc/nginx/nginx.conf unchanged.
set -eu
source=/etc/nginx/nginx.conf
dest=/tmp/aionex-nginx-fr09-realip.conf
trusted_dir=/etc/nginx/aionex-realip
if [ ! -r "$source" ] || [ ! -d "$trusted_dir" ]; then
    echo 'FR09 trusted-origin prerequisites unavailable' >&2
    exit 2
fi
# Add exactly one optional include inside the existing top-level http block.
# If no trusted peer is admitted, the glob contains no .conf and Nginx
# continues to use the actual TCP peer for its existing rate-limit zones.
awk '
    /^http \{$/ {
        seen += 1
        print
        print "    include /etc/nginx/aionex-realip/*.conf;"
        next
    }
    { print }
    END { if (seen != 1) exit 3 }
' "$source" > "$dest"
if [ "${1:-}" = '--check' ]; then
    exec nginx -t -c "$dest"
fi
nginx -t -c "$dest"
exec nginx -c "$dest" -g 'daemon off;'
