from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, BinaryIO, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthControlledPilot,
    GrowthSocialProviderCapability,
)
from app.services import growth_controlled_pilots as pilots
from app.services import growth_meta_owned_connector as meta_owned
from app.services import growth_meta_owned_write as meta_owned_write

META_PROVIDER = "meta"
META_CAPABILITY = "ads.manage"
ADAPTER_VERSION = "gs12-meta-live-adapter-v1"
MAX_JSON_BYTES = 32_768
MAX_NAME_LENGTH = 240
_ALLOWED_OBJECTIVES = {"OUTCOME_TRAFFIC"}
_ALLOWED_STATUS = {"PAUSED", "ACTIVE"}
_ALLOWED_BILLING_EVENTS = {"IMPRESSIONS", "LINK_CLICKS"}
_ALLOWED_OPTIMIZATION_GOALS = {"LINK_CLICKS", "LANDING_PAGE_VIEWS", "IMPRESSIONS"}
_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|_)(?:token|secret|password|authorization|api_key|apikey|private_key|credential)(?:$|_)",
    re.IGNORECASE,
)


class MetaLiveExecutionAdapterError(RuntimeError):
    """Fail-closed Meta live execution adapter error."""


@dataclass(frozen=True)
class MetaRequestSpec:
    method: str
    path: str
    form: dict[str, Any]
    operation: str

    def safe_shape(self) -> dict[str, Any]:
        """Return only reviewable field names; never values or provider object IDs."""
        return {
            "method": self.method,
            "operation": self.operation,
            "field_names": sorted(self.form),
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _numeric_id(value: str, label: str) -> str:
    clean = str(value or "").strip()
    if not clean.isdigit() or not (6 <= len(clean) <= 32):
        raise MetaLiveExecutionAdapterError(f"{label}-invalid")
    return clean


def _safe_name(value: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > MAX_NAME_LENGTH:
        raise MetaLiveExecutionAdapterError("name-invalid")
    lowered = clean.lower()
    if any(
        marker in lowered for marker in ("token=", "secret=", "password=", "bearer ")
    ):
        raise MetaLiveExecutionAdapterError("credential-material-forbidden")
    return clean


def _safe_json(value: Any, label: str) -> Any:
    def walk(item: Any, depth: int = 0) -> None:
        if depth > 8:
            raise MetaLiveExecutionAdapterError(f"{label}-too-deep")
        if isinstance(item, dict):
            if len(item) > 100:
                raise MetaLiveExecutionAdapterError(f"{label}-too-many-items")
            for key, nested in item.items():
                if not isinstance(key, str) or not key or _SENSITIVE_KEY_RE.search(key):
                    raise MetaLiveExecutionAdapterError("credential-material-forbidden")
                walk(nested, depth + 1)
            return
        if isinstance(item, list):
            if len(item) > 200:
                raise MetaLiveExecutionAdapterError(f"{label}-too-many-items")
            for nested in item:
                walk(nested, depth + 1)
            return
        if item is None or isinstance(item, (str, bool, int)):
            if isinstance(item, str):
                lowered = item.lower()
                if any(
                    marker in lowered
                    for marker in ("bearer ", "access_token=", "secret=", "password=")
                ):
                    raise MetaLiveExecutionAdapterError("credential-material-forbidden")
            return
        if isinstance(item, float) and math.isfinite(item):
            return
        raise MetaLiveExecutionAdapterError(f"{label}-unsupported-value")

    walk(value)
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise MetaLiveExecutionAdapterError(f"{label}-too-large")
    return value


def build_campaign_create(
    account_id: str,
    *,
    name: str,
    objective: str = "OUTCOME_TRAFFIC",
) -> MetaRequestSpec:
    account_id = _numeric_id(account_id, "ad-account-id")
    objective = str(objective or "").strip().upper()
    if objective not in _ALLOWED_OBJECTIVES:
        raise MetaLiveExecutionAdapterError("campaign-objective-not-allowlisted")
    return MetaRequestSpec(
        method="POST",
        path=f"/act_{account_id}/campaigns",
        operation="campaign.create_paused",
        form={
            "name": _safe_name(name),
            "objective": objective,
            "status": "PAUSED",
            "special_ad_categories": [],
            "is_adset_budget_sharing_enabled": False,
        },
    )


def build_adset_create(
    account_id: str,
    *,
    campaign_id: str,
    name: str,
    daily_budget_minor: int,
    targeting: dict[str, Any],
    billing_event: str = "IMPRESSIONS",
    optimization_goal: str = "LINK_CLICKS",
) -> MetaRequestSpec:
    account_id = _numeric_id(account_id, "ad-account-id")
    campaign_id = _numeric_id(campaign_id, "campaign-id")
    budget = int(daily_budget_minor)
    if budget <= 0 or budget > pilots.MAX_MONEY_MINOR:
        raise MetaLiveExecutionAdapterError("daily-budget-invalid")
    billing_event = str(billing_event or "").strip().upper()
    optimization_goal = str(optimization_goal or "").strip().upper()
    if billing_event not in _ALLOWED_BILLING_EVENTS:
        raise MetaLiveExecutionAdapterError("billing-event-not-allowlisted")
    if optimization_goal not in _ALLOWED_OPTIMIZATION_GOALS:
        raise MetaLiveExecutionAdapterError("optimization-goal-not-allowlisted")
    return MetaRequestSpec(
        method="POST",
        path=f"/act_{account_id}/adsets",
        operation="adset.create_paused",
        form={
            "name": _safe_name(name),
            "campaign_id": campaign_id,
            "daily_budget": budget,
            "billing_event": billing_event,
            "optimization_goal": optimization_goal,
            "targeting": _safe_json(dict(targeting or {}), "targeting"),
            "status": "PAUSED",
        },
    )


def build_creative_create(
    account_id: str,
    *,
    name: str,
    object_story_spec: dict[str, Any],
) -> MetaRequestSpec:
    account_id = _numeric_id(account_id, "ad-account-id")
    story = _safe_json(dict(object_story_spec or {}), "object-story-spec")
    if not story:
        raise MetaLiveExecutionAdapterError("object-story-spec-required")
    return MetaRequestSpec(
        method="POST",
        path=f"/act_{account_id}/adcreatives",
        operation="creative.create",
        form={"name": _safe_name(name), "object_story_spec": story},
    )


def build_ad_create(
    account_id: str,
    *,
    name: str,
    adset_id: str,
    creative_id: str,
) -> MetaRequestSpec:
    account_id = _numeric_id(account_id, "ad-account-id")
    adset_id = _numeric_id(adset_id, "adset-id")
    creative_id = _numeric_id(creative_id, "creative-id")
    return MetaRequestSpec(
        method="POST",
        path=f"/act_{account_id}/ads",
        operation="ad.create_paused",
        form={
            "name": _safe_name(name),
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED",
        },
    )


def build_status_update(object_id: str, status: str) -> MetaRequestSpec:
    object_id = _numeric_id(object_id, "provider-object-id")
    status = str(status or "").strip().upper()
    if status not in _ALLOWED_STATUS:
        raise MetaLiveExecutionAdapterError("status-not-allowlisted")
    return MetaRequestSpec(
        method="POST",
        path=f"/{object_id}",
        operation=f"object.status_{status.lower()}",
        form={"status": status},
    )


def _adapter_self_test_shapes() -> list[MetaRequestSpec]:
    account_id = "123456789012345"
    campaign_id = "223456789012345"
    adset_id = "323456789012345"
    creative_id = "423456789012345"
    ad_id = "523456789012345"
    specs = [
        build_campaign_create(account_id, name="AIONEX GS12 Adapter Dry Run"),
        build_adset_create(
            account_id,
            campaign_id=campaign_id,
            name="AIONEX GS12 Adapter Dry Run Ad Set",
            daily_budget_minor=100,
            targeting={"geo_locations": {"countries": ["AE"]}},
        ),
        build_creative_create(
            account_id,
            name="AIONEX GS12 Adapter Dry Run Creative",
            object_story_spec={
                "page_id": "623456789012345",
                "link_data": {
                    "link": "https://example.invalid/gs12-dry-run",
                    "message": "AIONEX GS12 adapter dry run",
                },
            },
        ),
        build_ad_create(
            account_id,
            name="AIONEX GS12 Adapter Dry Run Ad",
            adset_id=adset_id,
            creative_id=creative_id,
        ),
        build_status_update(ad_id, "PAUSED"),
        build_status_update(ad_id, "ACTIVE"),
    ]
    for spec in specs[:4]:
        if spec.form.get("status", "PAUSED") != "PAUSED":
            raise MetaLiveExecutionAdapterError("create-operation-must-start-paused")
    return specs


def adapter_contract_digest() -> str:
    shapes = [spec.safe_shape() for spec in _adapter_self_test_shapes()]
    raw = json.dumps(shapes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def verify_adapter_dry_run(
    session: AsyncSession,
    actor: UserRecord,
    pilot_id: str,
) -> dict[str, Any]:
    if actor.role != "Super Owner":
        raise MetaLiveExecutionAdapterError("super-owner-required")
    row = await session.scalar(
        select(GrowthControlledPilot)
        .where(GrowthControlledPilot.id == pilot_id)
        .with_for_update()
    )
    if row is None:
        raise MetaLiveExecutionAdapterError("pilot-not-found")
    if (
        row.mode != "live_spend"
        or row.provider != META_PROVIDER
        or row.provider_scope != "managed_ad_account"
        or not row.scope_ref
        or not row.organization_id
    ):
        raise MetaLiveExecutionAdapterError("pilot-not-live-meta-managed-account")

    capability = await session.scalar(
        select(GrowthSocialProviderCapability)
        .where(
            GrowthSocialProviderCapability.provider == META_PROVIDER,
            GrowthSocialProviderCapability.capability == META_CAPABILITY,
        )
        .with_for_update()
    )
    evidence = dict(capability.evidence or {}) if capability else {}
    if not (
        capability
        and capability.verification_state == pilots.LIVE_WRITE_VERIFICATION_STATE
        and capability.mutation_class == "write"
        and evidence.get("mutation_allowed") is True
        and evidence.get("live_scope_ref") == row.scope_ref
        and evidence.get("live_organization_id") == row.organization_id
        and evidence.get("live_no_spend_write_verified") is True
    ):
        raise MetaLiveExecutionAdapterError("live-write-verification-required")

    specs = _adapter_self_test_shapes()
    digest = adapter_contract_digest()
    evidence["execution_adapter_verified"] = True
    evidence["execution_adapter_scope_ref"] = row.scope_ref
    evidence["execution_adapter_organization_id"] = row.organization_id
    evidence["execution_adapter_version"] = ADAPTER_VERSION
    evidence["execution_adapter_contract_digest"] = digest
    evidence["execution_adapter_dry_run"] = True
    evidence["execution_adapter_provider_call_executed"] = False
    evidence["execution_adapter_spend_executed"] = False
    evidence["spend_allowed"] = False
    capability.evidence = evidence
    capability.version = int(capability.version or 0) + 1
    capability.verified_at = _now()

    pilot_evidence = dict(row.evidence or {})
    pilot_evidence["live_execution_adapter_verification"] = {
        "verified": True,
        "adapter_version": ADAPTER_VERSION,
        "contract_digest": digest,
        "provider_call_executed": False,
        "spend_executed": False,
        "automatic_execution_allowed": False,
    }
    row.evidence = pilot_evidence
    row.live_provider_mutation_allowed = False
    row.real_spend_allowed = False
    row.version += 1

    session.add(
        AuditEvent(
            organization_id=row.organization_id,
            user_id=actor.id,
            action="growth.pilot.live_execution_adapter_verified",
            resource_type="growth_controlled_pilot",
            resource_id=row.id,
            details={
                "provider": META_PROVIDER,
                "adapter_version": ADAPTER_VERSION,
                "contract_digest": digest,
                "request_shape_count": len(specs),
                "provider_call_executed": False,
                "spend_executed": False,
                "automatic_execution_allowed": False,
            },
        )
    )
    await session.flush()
    return {
        "pilot_id": row.id,
        "adapter_version": ADAPTER_VERSION,
        "contract_digest": digest,
        "request_shape_count": len(specs),
        "provider_call_executed": False,
        "spend_executed": False,
        "execution_adapter_verified": True,
        "real_spend_allowed": False,
        "automatic_execution_allowed": False,
    }


def _encode_form(form: dict[str, Any]) -> bytes:
    encoded: dict[str, str | int] = {}
    for key, value in form.items():
        if isinstance(value, (dict, list, bool)):
            encoded[key] = json.dumps(value, separators=(",", ":"))
        elif isinstance(value, (str, int)):
            encoded[key] = value
        else:
            raise MetaLiveExecutionAdapterError("request-form-value-unsupported")
    return urlencode(encoded).encode("utf-8")


def _normalized_provider_account_id(value: Any) -> str:
    clean = str(value or "").strip()
    if clean.startswith("act_"):
        clean = clean[4:]
    return _numeric_id(clean, "provider-account-id")


def _dependent_object_ids(request_spec: MetaRequestSpec) -> tuple[str, ...]:
    if request_spec.operation == "adset.create_paused":
        return (
            _numeric_id(str(request_spec.form.get("campaign_id") or ""), "campaign-id"),
        )
    if request_spec.operation == "ad.create_paused":
        creative = request_spec.form.get("creative")
        creative_id = (
            (creative or {}).get("creative_id") if isinstance(creative, dict) else None
        )
        return (
            _numeric_id(str(request_spec.form.get("adset_id") or ""), "adset-id"),
            _numeric_id(str(creative_id or ""), "creative-id"),
        )
    if request_spec.operation.startswith("object.status_"):
        return (_numeric_id(request_spec.path.lstrip("/"), "provider-object-id"),)
    return ()


def _read_provider_object_account(
    *,
    object_id: str,
    api_version: str,
    token: str,
    opener: Callable[..., BinaryIO],
) -> str:
    request = Request(
        f"https://graph.facebook.com/{api_version}/{object_id}?fields=id,account_id",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        response = opener(request, timeout=20)
        payload = json.load(response)
    except HTTPError as exc:
        raise _redacted_provider_error(exc, "ownership-read") from None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise MetaLiveExecutionAdapterError(
            f"meta-live-ownership-read-failed-{type(exc).__name__.lower()}"
        ) from None
    if not isinstance(payload, dict) or str(payload.get("id") or "") != object_id:
        raise MetaLiveExecutionAdapterError(
            "provider-object-ownership-response-invalid"
        )
    return _normalized_provider_account_id(payload.get("account_id"))


def _verify_dependency_account_binding(
    *,
    request_spec: MetaRequestSpec,
    account_id: str,
    api_version: str,
    token: str,
    opener: Callable[..., BinaryIO],
) -> None:
    for object_id in _dependent_object_ids(request_spec):
        owner_account_id = _read_provider_object_account(
            object_id=object_id,
            api_version=api_version,
            token=token,
            opener=opener,
        )
        if owner_account_id != account_id:
            raise MetaLiveExecutionAdapterError("provider-object-account-mismatch")


def _redacted_provider_error(
    exc: HTTPError, operation: str
) -> MetaLiveExecutionAdapterError:
    code: str | int = exc.code
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("code") is not None:
            code = error["code"]
    except (ValueError, OSError):
        code = exc.code
    return MetaLiveExecutionAdapterError(f"meta-live-{operation}-api-error-{code}")


async def execute_guarded_request(
    session: AsyncSession,
    *,
    pilot_id: str,
    scope_ref: str,
    account_id: str,
    request_spec: MetaRequestSpec,
    opener: Callable[..., BinaryIO] = urlopen,
) -> dict[str, Any]:
    """Execute one Meta mutation only after same-transaction runtime authorization.

    This function is intentionally not exposed by an HTTP route. It is a low-level
    provider adapter for a future explicitly controlled execution workflow.
    """

    account_id = _numeric_id(account_id, "ad-account-id")
    if meta_owned_write.opaque_scope_ref(account_id) != scope_ref:
        raise MetaLiveExecutionAdapterError("provider-scope-mismatch")
    if request_spec.method != "POST":
        raise MetaLiveExecutionAdapterError("unsupported-provider-method")
    if request_spec.path.startswith(
        f"/act_{account_id}/"
    ) is False and not re.fullmatch(r"/[0-9]{6,32}", request_spec.path):
        raise MetaLiveExecutionAdapterError("request-path-not-bound-to-provider-scope")

    authorization = await pilots.runtime_authorization(
        session,
        pilot_id,
        provider=META_PROVIDER,
        scope_ref=scope_ref,
    )
    if not authorization.get("authorized"):
        reasons = ",".join(authorization.get("blocked_reasons") or ["denied"])
        raise MetaLiveExecutionAdapterError(f"runtime-authorization-denied:{reasons}")

    if request_spec.operation == "adset.create_paused":
        budget = int(request_spec.form.get("daily_budget") or 0)
        maximum = int(authorization.get("max_daily_budget_minor") or 0)
        if budget <= 0 or maximum <= 0 or budget > maximum:
            raise MetaLiveExecutionAdapterError(
                "adset-daily-budget-exceeds-runtime-cap"
            )

    token_file, api_version = meta_owned._safe_config()
    token = meta_owned._read_token(token_file)
    try:
        _verify_dependency_account_binding(
            request_spec=request_spec,
            account_id=account_id,
            api_version=api_version,
            token=token,
            opener=opener,
        )
        request = Request(
            f"https://graph.facebook.com/{api_version}{request_spec.path}",
            data=_encode_form(request_spec.form),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            response = opener(request, timeout=20)
            payload = json.load(response)
        except HTTPError as exc:
            raise _redacted_provider_error(exc, request_spec.operation) from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise MetaLiveExecutionAdapterError(
                f"meta-live-{request_spec.operation}-failed-{type(exc).__name__.lower()}"
            ) from None
        if not isinstance(payload, dict):
            raise MetaLiveExecutionAdapterError("provider-response-invalid")
        return payload
    finally:
        token = ""
