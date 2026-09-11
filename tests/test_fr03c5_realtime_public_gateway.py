from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGINX = ROOT / "web-dashboard/docker/nginx.conf"


def _public_api_server(source: str) -> str:
    marker = "# Public API gateway. It deliberately never serves the dashboard frontend."
    start = source.index(marker)
    end = source.index("# Public user portal origin.", start)
    return source[start:end]


def test_public_gateway_exposes_only_authenticated_realtime_routes() -> None:
    source = NGINX.read_text(encoding="utf-8")
    public = _public_api_server(source)

    status = "location = /api/v1/realtime/status {"
    connect = "location = /api/v1/realtime/connect {"
    catch_all = "location /api/ {"
    assert status in public
    assert connect in public
    assert public.index(status) < public.index(catch_all)
    assert public.index(connect) < public.index(catch_all)

    connect_block = public[public.index(connect): public.index("        }", public.index(connect)) + 9]
    for required in (
        "access_log off;",
        "error_log /dev/null crit;",
        "proxy_http_version 1.1;",
        "proxy_set_header Upgrade $http_upgrade;",
        "proxy_set_header Connection $connection_upgrade;",
        "proxy_set_header X-AIOS-Auth-Channel public;",
        "proxy_buffering off;",
        "proxy_read_timeout 3600s;",
        "proxy_send_timeout 60s;",
        "proxy_hide_header Server;",
    ):
        assert required in connect_block


def test_public_gateway_blocks_legacy_process_local_websocket() -> None:
    public = _public_api_server(NGINX.read_text(encoding="utf-8"))
    legacy = "location /ws/ {"
    start = public.index(legacy)
    block = public[start: public.index("        }", start) + 9]
    assert "return 404;" in block
    assert "proxy_pass" not in block
    assert "proxy_set_header Upgrade" not in block


def test_realtime_status_keeps_public_auth_channel_and_gateway_limits() -> None:
    public = _public_api_server(NGINX.read_text(encoding="utf-8"))
    status = "location = /api/v1/realtime/status {"
    start = public.index(status)
    block = public[start: public.index("        }", start) + 9]
    for required in (
        "limit_req zone=api_per_ip burst=40 nodelay;",
        "limit_conn connections_per_ip 20;",
        "proxy_set_header X-AIOS-Auth-Channel public;",
        "proxy_hide_header Server;",
    ):
        assert required in block
