from __future__ import annotations

import json
from typing import Any, BinaryIO, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.services import growth_meta_owned_connector as owned
from app.services.growth_meta_owned_write import opaque_scope_ref

META_PROVIDER = "meta"
META_VALIDATION_MODE = "owned_target_discovery_read_only"
MAX_TARGETS = 100


class MetaTargetDiscoveryError(RuntimeError):
    """Redacted fail-closed error for Owner-only Meta target discovery."""


def _redacted_meta_error(exc: HTTPError, action: str) -> MetaTargetDiscoveryError:
    code: str | int = exc.code
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        meta_error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(meta_error, dict) and meta_error.get("code") is not None:
            code = meta_error["code"]
    except (ValueError, OSError):
        code = exc.code
    return MetaTargetDiscoveryError(f"meta-target-{action}-api-error-{code}")


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
        raise _redacted_meta_error(exc, action) from None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise MetaTargetDiscoveryError(
            f"meta-target-{action}-failed-{type(exc).__name__.lower()}"
        ) from None
    if not isinstance(payload, dict):
        raise MetaTargetDiscoveryError(f"meta-target-{action}-response-invalid")
    return payload


def _safe_text(value: object, *, max_length: int) -> str:
    clean = " ".join(str(value or "").split()).strip()
    if len(clean) > max_length:
        clean = clean[:max_length]
    return clean


def _account_item(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    raw_id = str(raw.get("id") or "").removeprefix("act_")
    if not raw_id.isdigit() or not (6 <= len(raw_id) <= 32):
        return None

    currency = _safe_text(raw.get("currency"), max_length=3).upper()
    if len(currency) != 3 or not currency.isalpha():
        currency = ""
    return {
        "scope_ref": opaque_scope_ref(raw_id),
        "name": _safe_text(raw.get("name"), max_length=200) or "Unnamed Meta account",
        "active": raw.get("account_status") == 1,
        "currency": currency or None,
        "timezone_name": _safe_text(raw.get("timezone_name"), max_length=100) or None,
    }


def resolve_scope_ref_to_raw_id(
    scope_ref: str,
    opener: Callable[..., BinaryIO] = urlopen,
) -> tuple[str, dict[str, Any]]:
    """Resolve one opaque managed-ad-account ref in memory without exposing the raw ID."""

    clean_ref = str(scope_ref or "").strip().lower()
    if not clean_ref.startswith("accountref://meta/sha256/") or len(clean_ref) != 89:
        raise MetaTargetDiscoveryError("meta-target-scope-reference-invalid")

    token_file, api_version = owned._safe_config()
    token = owned._read_token(token_file)
    try:
        accounts_request = Request(
            f"https://graph.facebook.com/{api_version}/me/adaccounts?"
            + urlencode(
                {
                    "fields": "id,name,account_status,currency,timezone_name",
                    "limit": str(MAX_TARGETS),
                }
            ),
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        accounts_payload = _request_json(
            accounts_request, action="scope-resolve", opener=opener
        )
        permissions_request = Request(
            f"https://graph.facebook.com/{api_version}/me/permissions",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        permissions_payload = _request_json(
            permissions_request, action="scope-permissions", opener=opener
        )
    finally:
        token = ""

    raw_accounts = accounts_payload.get("data")
    if not isinstance(raw_accounts, list):
        raise MetaTargetDiscoveryError("meta-target-scope-account-list-invalid")
    paging = accounts_payload.get("paging")
    if isinstance(paging, dict) and paging.get("next"):
        raise MetaTargetDiscoveryError("meta-target-scope-account-list-truncated")
    raw_permissions = permissions_payload.get("data")
    if not isinstance(raw_permissions, list):
        raise MetaTargetDiscoveryError("meta-target-scope-permission-list-invalid")
    granted = {
        str(item.get("permission"))
        for item in raw_permissions
        if isinstance(item, dict)
        and item.get("status") == "granted"
        and item.get("permission")
    }
    if "ads_management" not in granted:
        raise MetaTargetDiscoveryError("meta-target-ads-management-required")

    for raw in raw_accounts:
        if not isinstance(raw, dict):
            continue
        raw_id = str(raw.get("id") or "").removeprefix("act_")
        if not raw_id.isdigit() or not (6 <= len(raw_id) <= 32):
            continue
        if opaque_scope_ref(raw_id) != clean_ref:
            continue
        if raw.get("account_status") != 1:
            raise MetaTargetDiscoveryError("meta-target-scope-account-inactive")
        currency = _safe_text(raw.get("currency"), max_length=3).upper()
        timezone_name = _safe_text(raw.get("timezone_name"), max_length=100)
        if len(currency) != 3 or not currency.isalpha() or not timezone_name:
            raise MetaTargetDiscoveryError("meta-target-scope-metadata-invalid")
        return raw_id, {
            "currency": currency,
            "timezone_name": timezone_name,
            "ads_management": True,
            "provider_write_executed": False,
            "provider_spend_executed": False,
        }
    raise MetaTargetDiscoveryError("meta-target-scope-reference-not-found")


def probe_meta_owned_targets_read_only(
    opener: Callable[..., BinaryIO] = urlopen,
) -> dict[str, Any]:
    """Discover owned Meta ad accounts without returning raw IDs or credentials."""

    token_file, api_version = owned._safe_config()
    token = owned._read_token(token_file)
    try:
        accounts_request = Request(
            f"https://graph.facebook.com/{api_version}/me/adaccounts?"
            + urlencode(
                {
                    "fields": "id,name,account_status,currency,timezone_name",
                    "limit": str(MAX_TARGETS),
                }
            ),
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        accounts_payload = _request_json(
            accounts_request,
            action="account-list",
            opener=opener,
        )

        permissions_request = Request(
            f"https://graph.facebook.com/{api_version}/me/permissions",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        permissions_payload = _request_json(
            permissions_request,
            action="permission-read",
            opener=opener,
        )
    finally:
        token = ""

    raw_accounts = accounts_payload.get("data")
    if not isinstance(raw_accounts, list):
        raise MetaTargetDiscoveryError("meta-target-account-list-response-invalid")
    raw_permissions = permissions_payload.get("data")
    if not isinstance(raw_permissions, list):
        raise MetaTargetDiscoveryError("meta-target-permission-response-invalid")

    accounts = [
        item for raw in raw_accounts if (item := _account_item(raw)) is not None
    ]
    accounts.sort(key=lambda item: (not item["active"], item["name"].casefold()))

    granted = {
        str(item.get("permission"))
        for item in raw_permissions
        if isinstance(item, dict)
        and item.get("status") == "granted"
        and item.get("permission")
    }
    permissions = {
        "ads_read": "ads_read" in granted,
        "ads_management": "ads_management" in granted,
        "business_management": "business_management" in granted,
    }
    paging = accounts_payload.get("paging")
    paging_dict = paging if isinstance(paging, dict) else {}

    return {
        "provider": META_PROVIDER,
        "validation_mode": META_VALIDATION_MODE,
        "graph_api_version": api_version,
        "accounts": accounts,
        "account_count": len(accounts),
        "active_account_count": sum(1 for item in accounts if item["active"]),
        "result_page_truncated": bool(paging_dict.get("next")),
        "permissions": permissions,
        "owned_token_write_ready": permissions["ads_management"],
        "provider_call_allowed": True,
        "provider_write_executed": False,
        "provider_spend_executed": False,
        "raw_account_ids_returned": False,
        "raw_secret_returned": False,
    }
