from __future__ import annotations

import hashlib
import json
from typing import Any, BinaryIO, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.services import growth_meta_owned_connector as owned

META_PROVIDER = "meta"
META_PAGE_DISCOVERY_MODE = "owned_page_discovery_read_only"
MAX_PAGES = 100
_ALLOWED_TASKS = {
    "ADVERTISE",
    "ANALYZE",
    "CREATE_CONTENT",
    "MANAGE",
    "MESSAGING",
    "MODERATE",
}


class MetaPageDiscoveryError(RuntimeError):
    """Redacted fail-closed error for Owner-only Meta Page discovery."""


def _page_ref(raw_page_id: str) -> str:
    if not raw_page_id.isdigit() or not (6 <= len(raw_page_id) <= 32):
        raise MetaPageDiscoveryError("meta-page-id-invalid")
    digest = hashlib.sha256(f"meta-page:{raw_page_id}".encode("utf-8")).hexdigest()
    return f"pageref://meta/sha256/{digest}"


def _redacted_error(exc: HTTPError, action: str) -> MetaPageDiscoveryError:
    code: str | int = exc.code
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        meta_error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(meta_error, dict) and meta_error.get("code") is not None:
            code = meta_error["code"]
    except (ValueError, OSError):
        code = exc.code
    return MetaPageDiscoveryError(f"meta-page-{action}-api-error-{code}")


def _request_json(
    request: Request,
    *,
    action: str,
    opener: Callable[..., BinaryIO],
) -> dict[str, Any]:
    try:
        response = opener(request, timeout=20)
        payload = json.load(response)
    except HTTPError as exc:
        raise _redacted_error(exc, action) from None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise MetaPageDiscoveryError(
            f"meta-page-{action}-failed-{type(exc).__name__.lower()}"
        ) from None
    if not isinstance(payload, dict):
        raise MetaPageDiscoveryError(f"meta-page-{action}-response-invalid")
    return payload


def _safe_name(value: object) -> str:
    return " ".join(str(value or "Unnamed Meta Page").split())[:160]


def _safe_tasks(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        {
            task
            for raw in value
            if isinstance(raw, str) and (task := raw.strip().upper()) in _ALLOWED_TASKS
        }
    )


def probe_meta_pages_read_only(
    opener: Callable[..., BinaryIO] = urlopen,
) -> dict[str, Any]:
    """List accessible Pages as opaque references; never return raw Page IDs or token."""

    token_file, api_version = owned._safe_config()
    token = owned._read_token(token_file)
    try:
        pages_request = Request(
            f"https://graph.facebook.com/{api_version}/me/accounts?"
            + urlencode({"fields": "id,name,tasks", "limit": str(MAX_PAGES)}),
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        pages_payload = _request_json(
            pages_request,
            action="list",
            opener=opener,
        )

        permissions_request = Request(
            f"https://graph.facebook.com/{api_version}/me/permissions",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        permissions_payload = _request_json(
            permissions_request,
            action="permissions",
            opener=opener,
        )
    finally:
        token = ""

    raw_pages = pages_payload.get("data")
    raw_permissions = permissions_payload.get("data")
    if not isinstance(raw_pages, list):
        raise MetaPageDiscoveryError("meta-page-list-response-invalid")
    if not isinstance(raw_permissions, list):
        raise MetaPageDiscoveryError("meta-page-permission-response-invalid")

    pages: list[dict[str, Any]] = []
    for raw in raw_pages:
        if not isinstance(raw, dict):
            continue
        raw_id = str(raw.get("id") or "")
        if not raw_id.isdigit() or not (6 <= len(raw_id) <= 32):
            continue
        tasks = _safe_tasks(raw.get("tasks"))
        pages.append(
            {
                "page_ref": _page_ref(raw_id),
                "name": _safe_name(raw.get("name")),
                "tasks": tasks,
                "advertise_ready": "ADVERTISE" in tasks,
            }
        )
    pages.sort(key=lambda item: (not item["advertise_ready"], item["name"].casefold()))

    granted = {
        str(item.get("permission"))
        for item in raw_permissions
        if isinstance(item, dict)
        and item.get("status") == "granted"
        and item.get("permission")
    }
    paging = pages_payload.get("paging")
    paging_dict = paging if isinstance(paging, dict) else {}
    return {
        "provider": META_PROVIDER,
        "validation_mode": META_PAGE_DISCOVERY_MODE,
        "graph_api_version": api_version,
        "pages": pages,
        "page_count": len(pages),
        "advertise_ready_page_count": sum(
            1 for item in pages if item["advertise_ready"]
        ),
        "result_page_truncated": bool(paging_dict.get("next")),
        "permissions": {
            "pages_show_list": "pages_show_list" in granted,
            "pages_read_engagement": "pages_read_engagement" in granted,
            "pages_manage_ads": "pages_manage_ads" in granted,
            "business_management": "business_management" in granted,
        },
        "provider_call_allowed": True,
        "provider_write_executed": False,
        "provider_spend_executed": False,
        "raw_page_ids_returned": False,
        "raw_secret_returned": False,
    }


def resolve_page_ref_to_raw_id(
    page_ref: str,
    opener: Callable[..., BinaryIO] = urlopen,
) -> tuple[str, list[str]]:
    """Resolve an opaque Page reference in-memory. The raw ID must never be persisted/logged."""

    clean = str(page_ref or "").strip().lower()
    result = probe_meta_pages_read_only(opener=opener)
    if result.get("result_page_truncated") is True:
        raise MetaPageDiscoveryError("meta-page-inventory-truncated")

    token_file, api_version = owned._safe_config()
    token = owned._read_token(token_file)
    try:
        request = Request(
            f"https://graph.facebook.com/{api_version}/me/accounts?"
            + urlencode({"fields": "id,tasks", "limit": str(MAX_PAGES)}),
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        payload = _request_json(request, action="resolve", opener=opener)
    finally:
        token = ""

    raw_pages = payload.get("data")
    if not isinstance(raw_pages, list):
        raise MetaPageDiscoveryError("meta-page-resolve-response-invalid")
    for raw in raw_pages:
        if not isinstance(raw, dict):
            continue
        raw_id = str(raw.get("id") or "")
        if not raw_id.isdigit() or not (6 <= len(raw_id) <= 32):
            continue
        if _page_ref(raw_id) != clean:
            continue
        tasks = _safe_tasks(raw.get("tasks"))
        if "ADVERTISE" not in tasks:
            raise MetaPageDiscoveryError("meta-page-advertise-task-missing")
        return raw_id, tasks
    raise MetaPageDiscoveryError("meta-page-reference-not-found")
