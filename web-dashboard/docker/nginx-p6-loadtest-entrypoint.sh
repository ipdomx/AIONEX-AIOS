#!/bin/sh
# P6 gate 6.1 load-test window: fail-closed Nginx entrypoint.
#
# The attested /etc/nginx/nginx.conf is never edited. A private copy in /tmp:
#   1. includes the FR09 trusted Cloudflare real-IP config (REQUIRED: without it
#      every client shares the tunnel peer address, so an exemption would
#      exempt the whole internet), and
#   2. keys the api_per_ip, auth_per_ip and connections_per_ip zones on
#      $aionex_p6_limit_key, which is empty (= not limited) only for the
#      operator-rendered load-generator addresses in exempt.conf and is
#      $binary_remote_addr for everyone else.
# exempt.conf must carry an unexpired "# expires_epoch=" line; an expired or
# malformed file refuses to start Nginx. Render it with
# scripts/capacity/p6_loadtest_exemption.py.
set -eu
source=${P6_NGINX_SOURCE:-/etc/nginx/nginx.conf}
dest=${P6_NGINX_DEST:-/tmp/aionex-nginx-p6-loadtest.conf}
realip_dir=${P6_NGINX_REALIP_DIR:-/etc/nginx/aionex-realip}
exempt_dir=${P6_NGINX_EXEMPT_DIR:-/etc/nginx/aionex-p6-loadtest}
exempt="$exempt_dir/exempt.conf"

fail() {
    echo "P6 load-test window refused: $1" >&2
    exit 2
}

[ -r "$source" ] || fail 'source nginx.conf unavailable'
found_realip=0
for candidate in "$realip_dir"/*.conf; do
    [ -r "$candidate" ] && found_realip=1
done
[ "$found_realip" = 1 ] || fail 'FR09 trusted real-IP config is not admitted'
grep -q '^real_ip_header CF-Connecting-IP;$' "$realip_dir"/*.conf || fail 'real-IP header is not CF-Connecting-IP'
[ -r "$exempt" ] || fail 'exempt.conf unavailable'
if grep -Ev '^(# expires_epoch=[0-9]{10}|# [A-Za-z0-9 ._:-]{0,120}|[0-9]{1,3}(\.[0-9]{1,3}){3}/32 1;|[0-9a-f:]{2,39}/128 1;)$' "$exempt" | grep -q .; then
    fail 'exempt.conf contains an unexpected line'
fi
entries=$(grep -Ec '^[0-9a-f:.]+/(32|128) 1;$' "$exempt" || true)
[ "$entries" -ge 1 ] && [ "$entries" -le 4 ] || fail 'exempt.conf must list 1 to 4 addresses'
expires=$(sed -n 's/^# expires_epoch=\([0-9]\{10\}\)$/\1/p' "$exempt" | head -n 1)
[ -n "$expires" ] || fail 'exempt.conf has no expiry'
now=$(date +%s)
[ "$now" -lt "$expires" ] || fail 'exempt.conf has expired'

awk -v exempt="$exempt" -v realip="$realip_dir" '
    /^http \{$/ {
        seen += 1
        print
        print "    include " realip "/*.conf;"
        print "    geo $aionex_p6_loadtest_source {"
        print "        default 0;"
        print "        include " exempt ";"
        print "    }"
        print "    map $aionex_p6_loadtest_source $aionex_p6_limit_key {"
        print "        1 \"\";"
        print "        default $binary_remote_addr;"
        print "    }"
        next
    }
    /^    limit_req_zone \$binary_remote_addr zone=(api_per_ip|auth_per_ip):/ {
        sub(/\$binary_remote_addr/, "$aionex_p6_limit_key")
        keyed += 1
    }
    /^    limit_conn_zone \$binary_remote_addr zone=connections_per_ip:/ {
        sub(/\$binary_remote_addr/, "$aionex_p6_limit_key")
        keyed += 1
    }
    { print }
    END { if (seen != 1 || keyed != 3) exit 3 }
' "$source" > "$dest" || fail 'nginx.conf layout changed; refusing to guess'

case "${1:-}" in
    --render) exit 0 ;;
    --check) exec nginx -t -c "$dest" ;;
esac
nginx -t -c "$dest"
exec nginx -c "$dest" -g 'daemon off;'
