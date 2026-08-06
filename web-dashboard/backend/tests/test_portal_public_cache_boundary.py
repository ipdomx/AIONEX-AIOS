"""Public portal caching is the only exception to the API no-store boundary."""

from __future__ import annotations

from main import _preserve_public_api_cache
from starlette.requests import Request
from starlette.responses import Response


def _request(path: str, method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("api.vip-e.net", 443),
        }
    )


def _response(
    cache_control: str,
    *,
    status_code: int = 200,
) -> Response:
    return Response(
        status_code=status_code,
        headers={"Cache-Control": cache_control},
    )


def test_published_configuration_preserves_public_cache_and_304() -> None:
    request = _request("/api/v1/portal/published")
    assert _preserve_public_api_cache(
        request,
        _response("public, max-age=60, stale-while-revalidate=300"),
    )
    assert _preserve_public_api_cache(
        request,
        _response(
            "public, max-age=60, stale-while-revalidate=300",
            status_code=304,
        ),
    )


def test_valid_portal_asset_preserves_immutable_public_cache() -> None:
    request = _request("/api/v1/portal/assets/" + "a" * 32)
    assert _preserve_public_api_cache(
        request,
        _response("public, max-age=31536000, immutable"),
    )


def test_private_mutation_error_and_unlisted_paths_never_preserve_cache() -> None:
    public_header = "public, max-age=60"
    assert not _preserve_public_api_cache(
        _request("/api/v1/portal/published", method="POST"),
        _response(public_header),
    )
    assert not _preserve_public_api_cache(
        _request("/api/v1/portal/published"),
        _response(public_header, status_code=500),
    )
    assert not _preserve_public_api_cache(
        _request("/api/v1/owner/portal"),
        _response(public_header),
    )
    assert not _preserve_public_api_cache(
        _request("/api/v1/portal/assets/not-a-valid-id"),
        _response("public, max-age=31536000, immutable"),
    )


def test_endpoint_must_explicitly_opt_into_public_cache() -> None:
    request = _request("/api/v1/portal/published")
    assert not _preserve_public_api_cache(request, _response("no-store"))
    assert not _preserve_public_api_cache(request, _response("private, max-age=60"))
    assert not _preserve_public_api_cache(request, _response(""))
