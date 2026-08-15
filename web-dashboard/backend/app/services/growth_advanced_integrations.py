from __future__ import annotations

import csv
import hashlib
import io
import ipaddress
import json
import re
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthCampaignBrief,
    GrowthContentItem,
    GrowthInboxThread,
    GrowthIntegrationConnection,
    GrowthLeadRecord,
    GrowthPaidCampaign,
    GrowthPerformanceObservation,
    GrowthReportDefinition,
    GrowthReportRun,
    GrowthSocialAccount,
    GrowthSocialProviderCapability,
    GrowthTeamAssignment,
    Team,
    TeamMembership,
    User,
)
from app.services import growth_access, growth_provider_connectors

INTEGRATION_TYPES = {"webhook", "crm", "email", "cloud", "sheets"}
REPORT_TYPES = {"executive", "provider_health", "team_workload"}
EXPORT_FORMATS = {"json", "csv", "xlsx", "pdf"}
SCHEDULE_KINDS = {"manual", "daily", "weekly", "monthly"}
RAW_SECRET_MARKERS = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
    "bearer",
    "credential_value",
)
EXTERNAL_DELIVERY_ALLOWED = False
LIVE_PROVIDER_CALL = False
REAL_SPEND_ALLOWED = False
MESSAGE_SEND_ALLOWED = False
LIVE_DOMAIN_ALLOWED = False


class GrowthAdvancedError(RuntimeError):
    """Fail-closed GS-10 advanced integration/export error."""


GrowthAdvancedIntegrationError = GrowthAdvancedError


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _require(
    session: AsyncSession, actor: UserRecord, capability: str
) -> growth_access.GrowthAccessDecision:
    decision = await growth_access.effective_access(session, actor, capability)
    if not decision.allowed:
        raise GrowthAdvancedError(f"access-denied:{decision.reason}")
    return decision


async def _audit(
    session: AsyncSession,
    actor: UserRecord,
    action: str,
    resource_type: str,
    resource_id: str | None,
    details: dict[str, Any],
) -> None:
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
    )


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 2000:
            raise GrowthAdvancedError("config-value-too-long")
        lowered = value.lower()
        if any(
            marker in lowered
            for marker in ("bearer ", "token=", "secret=", "password=")
        ):
            raise GrowthAdvancedError("raw-secret-field-forbidden")
        return value
    if isinstance(value, list):
        if len(value) > 100:
            raise GrowthAdvancedError("config-list-too-large")
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if any(marker in name.lower() for marker in RAW_SECRET_MARKERS):
                raise GrowthAdvancedError("raw-secret-field-forbidden")
            clean[name] = _safe_value(item)
        return clean
    raise GrowthAdvancedError("unsupported-config-value")


def _validate_webhook(config: dict[str, Any]) -> dict[str, Any]:
    clean = dict(_safe_value(config))
    endpoint = str(clean.get("endpoint") or clean.get("url") or "").strip()
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise GrowthAdvancedError("webhook-https-required")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GrowthAdvancedError("webhook-credentials-query-fragment-forbidden")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise GrowthAdvancedError("webhook-private-host-forbidden")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise GrowthAdvancedError("webhook-private-host-forbidden")
    port = f":{parsed.port}" if parsed.port else ""
    clean["endpoint"] = f"https://{host}{port}{parsed.path or '/'}"
    clean.pop("url", None)
    return clean


def _safe_resource_ref(value: str) -> str:
    ref = value.strip()
    if not re.fullmatch(r"resource://[A-Za-z0-9._~:/-]{3,500}", ref):
        raise GrowthAdvancedError("invalid-resource-reference")
    return ref


def _safe_domain(value: str | None) -> str | None:
    if not value:
        return None
    domain = value.strip().lower().rstrip(".")
    if len(domain) > 253 or ":" in domain or "/" in domain:
        raise GrowthAdvancedError("invalid-custom-domain")
    labels = domain.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise GrowthAdvancedError("invalid-custom-domain")
    return domain


def _safe_timezone(value: str) -> str:
    name = value.strip() or "UTC"
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise GrowthAdvancedError("invalid-timezone") from None
    return name


def _next_run(kind: str, base: datetime | None = None) -> datetime | None:
    now = base or _now()
    if kind == "manual":
        return None
    if kind == "daily":
        return now + timedelta(days=1)
    if kind == "weekly":
        return now + timedelta(days=7)
    if kind == "monthly":
        return now + timedelta(days=30)
    raise GrowthAdvancedError("unsupported-schedule-kind")


def _safe_permissions(values: list[Any]) -> list[str]:
    result: list[str] = []
    for item in values:
        value = str(item).strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,79}", value):
            raise GrowthAdvancedError("invalid-team-permission")
        if value not in result:
            result.append(value)
    return sorted(result)


async def create_integration(
    session: AsyncSession, actor: UserRecord, payload: dict[str, Any]
) -> GrowthIntegrationConnection:
    await _require(session, actor, "integrations.manage")
    integration_type = str(payload.get("integration_type") or "").strip().lower()
    if integration_type not in INTEGRATION_TYPES:
        raise GrowthAdvancedError("unsupported-integration-type")
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 160:
        raise GrowthAdvancedError("invalid-integration-name")
    provider = str(payload.get("provider") or "generic").strip().lower()
    if not provider or len(provider) > 80:
        raise GrowthAdvancedError("invalid-integration-provider")
    credential_ref = payload.get("credential_ref")
    if credential_ref:
        ok, reason = growth_provider_connectors.validate_credential_ref(
            str(credential_ref)
        )
        if not ok:
            raise GrowthAdvancedError(reason)
        credential_ref = str(credential_ref)
    config = dict(_safe_value(dict(payload.get("config") or {})))
    if integration_type == "webhook":
        config = _validate_webhook(config)
    elif "resource_ref" in config:
        config["resource_ref"] = _safe_resource_ref(str(config["resource_ref"]))
    capabilities = _safe_permissions(list(payload.get("capabilities") or []))
    if not capabilities:
        capabilities = [f"{integration_type}.simulation"]
    row = GrowthIntegrationConnection(
        organization_id=actor.organization_id,
        created_by_id=actor.id,
        integration_type=integration_type,
        provider=provider,
        name=name,
        credential_ref=credential_ref,
        status="draft",
        config=config,
        capabilities=capabilities,
        external_delivery_allowed=False,
        live_provider_call=False,
        version=1,
    )
    session.add(row)
    await session.flush()
    await _audit(
        session,
        actor,
        "growth.integration.created",
        "growth_integration",
        row.id,
        {
            "integration_type": integration_type,
            "provider": provider,
            "credential_configured": bool(credential_ref),
            "external_delivery_allowed": False,
            "live_provider_call": False,
        },
    )
    return row


async def simulate_integration(
    session: AsyncSession, actor: UserRecord, integration_id: str
) -> dict[str, Any]:
    await _require(session, actor, "integrations.manage")
    row = await session.scalar(
        select(GrowthIntegrationConnection).where(
            GrowthIntegrationConnection.id == integration_id,
            GrowthIntegrationConnection.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise GrowthAdvancedError("integration-not-found")
    row.status = "simulated"
    row.last_simulated_at = _now()
    row.external_delivery_allowed = False
    row.live_provider_call = False
    row.version = int(row.version or 0) + 1
    await session.flush()
    evidence = {
        "id": row.id,
        "integration_type": row.integration_type,
        "provider": row.provider,
        "simulation_only": True,
        "provider_call_allowed": False,
        "external_delivery_allowed": False,
        "message_send_allowed": False,
        "webhook_delivery_allowed": False,
        "raw_secret_persisted": False,
    }
    await _audit(
        session,
        actor,
        "growth.integration.simulated",
        "growth_integration",
        row.id,
        evidence,
    )
    return evidence


async def list_integrations(
    session: AsyncSession, actor: UserRecord
) -> list[GrowthIntegrationConnection]:
    await _require(session, actor, "integrations.manage")
    rows = await session.scalars(
        select(GrowthIntegrationConnection)
        .where(GrowthIntegrationConnection.organization_id == actor.organization_id)
        .order_by(GrowthIntegrationConnection.created_at.desc())
    )
    return list(rows)


def public_integration(row: GrowthIntegrationConnection) -> dict[str, Any]:
    return {
        "id": row.id,
        "integration_type": row.integration_type,
        "provider": row.provider,
        "name": row.name,
        "status": row.status,
        "capabilities": list(row.capabilities or []),
        "credential_configured": bool(row.credential_ref),
        "external_delivery_allowed": False,
        "live_provider_call": False,
        "last_simulated_at": row.last_simulated_at,
    }


async def upsert_team_assignment(
    session: AsyncSession, actor: UserRecord, payload: dict[str, Any]
) -> GrowthTeamAssignment:
    await _require(session, actor, "teams.manage")
    user_id = str(payload.get("user_id") or "").strip()
    user = await session.scalar(
        select(User).where(
            User.id == user_id,
            User.organization_id == actor.organization_id,
            User.status.in_(["active", "online"]),
        )
    )
    if user is None:
        raise GrowthAdvancedError("team-assignment-user-not-found")
    team_id = payload.get("team_id")
    if team_id:
        team = await session.scalar(
            select(Team).where(
                Team.id == str(team_id),
                Team.organization_id == actor.organization_id,
                Team.status == "active",
            )
        )
        if team is None:
            raise GrowthAdvancedError("team-not-found")
        membership = await session.scalar(
            select(TeamMembership).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == user.id,
            )
        )
        if membership is None:
            raise GrowthAdvancedError("team-membership-required")
        team_id = team.id
    scope_type = str(payload.get("scope_type") or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,39}", scope_type):
        raise GrowthAdvancedError("invalid-team-scope")
    scope_id = str(payload.get("scope_id") or "").strip()
    if not scope_id or len(scope_id) > 160:
        raise GrowthAdvancedError("invalid-team-scope-id")
    role_key = str(payload.get("role_key") or "viewer").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,31}", role_key):
        raise GrowthAdvancedError("invalid-team-role")
    permissions = _safe_permissions(list(payload.get("permissions") or []))
    row = await session.scalar(
        select(GrowthTeamAssignment).where(
            GrowthTeamAssignment.organization_id == actor.organization_id,
            GrowthTeamAssignment.user_id == user.id,
            GrowthTeamAssignment.scope_type == scope_type,
            GrowthTeamAssignment.scope_id == scope_id,
        )
    )
    if row is None:
        row = GrowthTeamAssignment(
            organization_id=actor.organization_id,
            user_id=user.id,
            team_id=team_id,
            created_by_id=actor.id,
            scope_type=scope_type,
            scope_id=scope_id,
            role_key=role_key,
            permissions=permissions,
            approval_required=bool(payload.get("approval_required", False)),
            active=True,
            version=1,
        )
        session.add(row)
    else:
        row.team_id = team_id
        row.role_key = role_key
        row.permissions = permissions
        row.approval_required = bool(payload.get("approval_required", False))
        row.active = True
        row.version = int(row.version or 0) + 1
    await session.flush()
    await _audit(
        session,
        actor,
        "growth.team.assignment.upserted",
        "growth_team_assignment",
        row.id,
        {
            "scope_type": scope_type,
            "role_key": role_key,
            "permissions": permissions,
            "approval_required": bool(row.approval_required),
        },
    )
    return row


def public_team_assignment(row: GrowthTeamAssignment) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "team_id": row.team_id,
        "scope_type": row.scope_type,
        "scope_id": row.scope_id,
        "role_key": row.role_key,
        "permissions": list(row.permissions or []),
        "approval_required": bool(row.approval_required),
        "active": bool(row.active),
    }


async def list_team_assignments(
    session: AsyncSession, actor: UserRecord
) -> list[GrowthTeamAssignment]:
    await _require(session, actor, "teams.manage")
    rows = await session.scalars(
        select(GrowthTeamAssignment)
        .where(GrowthTeamAssignment.organization_id == actor.organization_id)
        .order_by(GrowthTeamAssignment.created_at.desc())
    )
    return list(rows)


async def simulate_team_routing(
    session: AsyncSession, actor: UserRecord, scope_type: str, scope_id: str
) -> dict[str, Any]:
    await _require(session, actor, "teams.manage")
    rows = await session.scalars(
        select(GrowthTeamAssignment)
        .where(
            GrowthTeamAssignment.organization_id == actor.organization_id,
            GrowthTeamAssignment.scope_type == scope_type,
            GrowthTeamAssignment.scope_id == scope_id,
            GrowthTeamAssignment.active.is_(True),
        )
        .order_by(GrowthTeamAssignment.user_id)
    )
    assignments = list(rows)
    chosen = assignments[0] if assignments else None
    return {
        "matched_assignments": len(assignments),
        "recommended_user_id": chosen.user_id if chosen else None,
        "recommended_role": chosen.role_key if chosen else None,
        "approval_required": bool(chosen.approval_required) if chosen else False,
        "assignment_applied": False,
        "provider_call_allowed": False,
        "external_mutation_allowed": False,
    }


def _validate_formats(values: list[Any]) -> list[str]:
    formats: list[str] = []
    for item in values:
        value = str(item).strip().lower()
        if value not in EXPORT_FORMATS:
            raise GrowthAdvancedError("unsupported-export-format")
        if value not in formats:
            formats.append(value)
    return formats or ["json"]


async def create_report_definition(
    session: AsyncSession, actor: UserRecord, payload: dict[str, Any]
) -> GrowthReportDefinition:
    await _require(session, actor, "reports.manage")
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 180:
        raise GrowthAdvancedError("invalid-report-name")
    report_type = str(payload.get("report_type") or "executive").strip().lower()
    if report_type not in REPORT_TYPES:
        raise GrowthAdvancedError("unsupported-report-type")
    formats = _validate_formats(list(payload.get("formats") or []))
    schedule_kind = str(payload.get("schedule_kind") or "manual").strip().lower()
    if schedule_kind not in SCHEDULE_KINDS:
        raise GrowthAdvancedError("unsupported-schedule-kind")
    if schedule_kind != "manual":
        await _require(session, actor, "automations.manage")
    timezone_name = _safe_timezone(
        str(payload.get("timezone") or payload.get("timezone_name") or "UTC")
    )
    filters = dict(_safe_value(dict(payload.get("filters") or {})))
    branding = dict(_safe_value(dict(payload.get("branding") or {})))
    custom_domain = _safe_domain(payload.get("custom_domain"))
    row = GrowthReportDefinition(
        organization_id=actor.organization_id,
        created_by_id=actor.id,
        name=name,
        report_type=report_type,
        formats=formats,
        filters=filters,
        schedule_kind=schedule_kind,
        timezone_name=timezone_name,
        next_run_at=_next_run(schedule_kind),
        active=True,
        brand_name=(str(payload.get("brand_name") or "").strip() or None),
        custom_domain=custom_domain,
        branding=branding,
        external_delivery_allowed=False,
        version=1,
    )
    session.add(row)
    await session.flush()
    await _audit(
        session,
        actor,
        "growth.report.definition.created",
        "growth_report_definition",
        row.id,
        {
            "report_type": report_type,
            "formats": formats,
            "schedule_kind": schedule_kind,
            "custom_domain_candidate": bool(custom_domain),
            "domain_verification_state": "unverified",
            "live_domain_allowed": False,
            "external_delivery_allowed": False,
        },
    )
    return row


async def list_report_definitions(
    session: AsyncSession, actor: UserRecord
) -> list[GrowthReportDefinition]:
    await _require(session, actor, "reports.manage")
    rows = await session.scalars(
        select(GrowthReportDefinition)
        .where(GrowthReportDefinition.organization_id == actor.organization_id)
        .order_by(GrowthReportDefinition.created_at.desc())
    )
    return list(rows)


def public_report_definition(row: GrowthReportDefinition) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "report_type": row.report_type,
        "formats": list(row.formats or []),
        "schedule_kind": row.schedule_kind,
        "timezone": row.timezone_name,
        "next_run_at": row.next_run_at,
        "active": bool(row.active),
        "brand_name": row.brand_name,
        "custom_domain": row.custom_domain,
        "domain_verification_state": (
            "unverified" if row.custom_domain else "not_configured"
        ),
        "live_domain_allowed": False,
        "external_delivery_allowed": False,
    }


async def _count_org(session: AsyncSession, model: Any, organization_id: str) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(model)
        .where(model.organization_id == organization_id)
    )
    return int(value or 0)


async def _summary(session: AsyncSession, organization_id: str) -> dict[str, Any]:
    integrations = await _count_org(
        session, GrowthIntegrationConnection, organization_id
    )
    assignments = int(
        await session.scalar(
            select(func.count())
            .select_from(GrowthTeamAssignment)
            .where(
                GrowthTeamAssignment.organization_id == organization_id,
                GrowthTeamAssignment.active.is_(True),
            )
        )
        or 0
    )
    return {
        "integrations": integrations,
        "active_team_assignments": assignments,
        "campaign_briefs": await _count_org(
            session, GrowthCampaignBrief, organization_id
        ),
        "content_items": await _count_org(session, GrowthContentItem, organization_id),
        "lead_records": await _count_org(session, GrowthLeadRecord, organization_id),
        "inbox_threads": await _count_org(session, GrowthInboxThread, organization_id),
        "performance_observations": await _count_org(
            session, GrowthPerformanceObservation, organization_id
        ),
        "paid_campaigns": await _count_org(
            session, GrowthPaidCampaign, organization_id
        ),
        "social_accounts": await _count_org(
            session, GrowthSocialAccount, organization_id
        ),
        "real_spend_allowed": False,
        "external_delivery_allowed": False,
    }


async def _provider_health(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(
        select(
            GrowthSocialProviderCapability.provider,
            GrowthSocialProviderCapability.verification_state,
            func.count(GrowthSocialProviderCapability.id),
        )
        .group_by(
            GrowthSocialProviderCapability.provider,
            GrowthSocialProviderCapability.verification_state,
        )
        .order_by(
            GrowthSocialProviderCapability.provider,
            GrowthSocialProviderCapability.verification_state,
        )
    )
    return [
        {
            "provider": provider,
            "verification_state": state,
            "capability_count": int(count),
        }
        for provider, state, count in result.all()
    ]


async def _team_workload(
    session: AsyncSession, organization_id: str
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(
            GrowthTeamAssignment.role_key,
            func.count(GrowthTeamAssignment.id),
        )
        .where(
            GrowthTeamAssignment.organization_id == organization_id,
            GrowthTeamAssignment.active.is_(True),
        )
        .group_by(GrowthTeamAssignment.role_key)
        .order_by(GrowthTeamAssignment.role_key)
    )
    return [
        {"role": role, "active_assignments": int(count)} for role, count in result.all()
    ]


def _snapshot(
    definition: GrowthReportDefinition,
    summary: dict[str, Any],
    details: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "schema": "aionex.growth.report.v1",
        "name": definition.name,
        "report_type": definition.report_type,
        "generated_at": generated_at.isoformat(),
        "branding": {
            "brand_name": definition.brand_name or "AIONEX AIOS",
            "custom_domain": definition.custom_domain,
            "domain_verification_state": (
                "unverified" if definition.custom_domain else "not_configured"
            ),
            "live_domain_allowed": False,
            "config": dict(definition.branding or {}),
        },
        "summary": summary,
        "details": details,
        "privacy": {
            "aggregate_only": True,
            "raw_credentials_exported": False,
            "lead_contact_pii_exported": False,
        },
        "safety": {
            "external_delivery_allowed": False,
            "live_provider_call": False,
            "message_send_allowed": False,
            "real_spend_allowed": False,
        },
    }


def _json_bytes(snapshot: dict[str, Any]) -> bytes:
    return json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _csv_bytes(snapshot: dict[str, Any]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    safety = dict(snapshot.get("safety") or {})
    summary = dict(snapshot.get("summary") or {})
    rows = [
        (
            "external_delivery_allowed",
            str(bool(safety.get("external_delivery_allowed"))).lower(),
        ),
        ("live_provider_call", str(bool(safety.get("live_provider_call"))).lower()),
        ("message_send_allowed", str(bool(safety.get("message_send_allowed"))).lower()),
        ("real_spend_allowed", str(bool(safety.get("real_spend_allowed"))).lower()),
    ]
    rows.extend((str(key), str(value)) for key, value in sorted(summary.items()))
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _excel_column(index: int) -> str:
    value = index + 1
    out = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        out = chr(65 + remainder) + out
    return out


def _zip_write(archive: zipfile.ZipFile, name: str, content: str) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content.encode("utf-8"))


def _xlsx_bytes(snapshot: dict[str, Any]) -> bytes:
    summary = dict(snapshot.get("summary") or {})
    rows: list[list[Any]] = [["metric", "value"]]
    rows.extend([[key, value] for key, value in sorted(summary.items())])
    rows.extend(
        [
            ["external_delivery_allowed", False],
            ["live_provider_call", False],
            ["message_send_allowed", False],
            ["real_spend_allowed", False],
        ]
    )
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row):
            ref = f"{_excel_column(column_index)}{row_index}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(str(value))}</t></is></c>'
            )
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    )

    def deterministic_write(archive: zipfile.ZipFile, name: str, data: str) -> None:
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        archive.writestr(info, data.encode("utf-8"))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        deterministic_write(
            archive,
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        deterministic_write(
            archive,
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        deterministic_write(
            archive,
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        deterministic_write(
            archive,
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        deterministic_write(archive, "xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_bytes(snapshot: dict[str, Any]) -> bytes:
    lines = [
        str((snapshot.get("branding") or {}).get("brand_name") or "AIONEX AIOS"),
        str(snapshot.get("name") or "Growth Report"),
        f"Report type: {snapshot.get('report_type', '')}",
        "",
    ]
    for key, value in sorted(dict(snapshot.get("summary") or {}).items()):
        lines.append(f"{key}: {value}")
    lines.extend(
        [
            "external_delivery_allowed: false",
            "live_provider_call: false",
            "message_send_allowed: false",
            "real_spend_allowed: false",
        ]
    )
    lines = [
        line.encode("latin-1", errors="replace").decode("latin-1")[:110]
        for line in lines[:45]
    ]
    content_parts = ["BT", "/F1 10 Tf", "50 780 Td"]
    for index, line in enumerate(lines):
        if index:
            content_parts.append("0 -16 Td")
        content_parts.append(f"({_pdf_escape(line)}) Tj")
    content_parts.append("ET")
    content = "\n".join(content_parts).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
        + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{index} 0 obj\n".encode("ascii"))
        output.write(obj)
        output.write(b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return output.getvalue()


def render_artifact(
    format_name: str, snapshot: dict[str, Any]
) -> tuple[bytes, str, str]:
    name = (
        re.sub(
            r"[^a-z0-9]+", "-", str(snapshot.get("name") or "growth-report").lower()
        ).strip("-")
        or "growth-report"
    )
    if format_name == "json":
        return _json_bytes(snapshot), "application/json", f"{name}.json"
    if format_name == "csv":
        return _csv_bytes(snapshot), "text/csv; charset=utf-8", f"{name}.csv"
    if format_name == "xlsx":
        return (
            _xlsx_bytes(snapshot),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"{name}.xlsx",
        )
    if format_name == "pdf":
        return _pdf_bytes(snapshot), "application/pdf", f"{name}.pdf"
    raise GrowthAdvancedError("unsupported-export-format")


def _manifest(formats: list[str], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for format_name in formats:
        data, media_type, filename = render_artifact(format_name, snapshot)
        items.append(
            {
                "format": format_name,
                "filename": filename,
                "media_type": media_type,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "local_generation_only": True,
                "external_delivery_allowed": False,
            }
        )
    return items


async def run_report(
    session: AsyncSession,
    actor: UserRecord,
    definition_id: str,
    *,
    trigger: str = "manual",
) -> GrowthReportRun:
    await _require(session, actor, "reports.manage")
    await _require(session, actor, "exports.create")
    definition = await session.scalar(
        select(GrowthReportDefinition).where(
            GrowthReportDefinition.id == definition_id,
            GrowthReportDefinition.organization_id == actor.organization_id,
            GrowthReportDefinition.active.is_(True),
        )
    )
    if definition is None:
        raise GrowthAdvancedError("report-definition-not-found")
    summary = await _summary(session, actor.organization_id)
    if definition.report_type == "provider_health":
        details = await _provider_health(session)
    elif definition.report_type == "team_workload":
        details = await _team_workload(session, actor.organization_id)
    else:
        details = []
    generated_at = _now()
    snapshot = _snapshot(definition, summary, details, generated_at)
    manifest = _manifest(list(definition.formats or ["json"]), snapshot)
    row = GrowthReportRun(
        organization_id=actor.organization_id,
        report_definition_id=definition.id,
        triggered_by_id=actor.id,
        status="completed",
        data_snapshot=snapshot,
        summary=summary,
        artifact_manifest=manifest,
        simulated=True,
        external_delivery_allowed=False,
        generated_at=generated_at,
        version=1,
    )
    session.add(row)
    if trigger == "schedule":
        definition.next_run_at = _next_run(definition.schedule_kind, generated_at)
        definition.version = int(definition.version or 0) + 1
    await session.flush()
    await _audit(
        session,
        actor,
        "growth.report.generated",
        "growth_report_run",
        row.id,
        {
            "report_type": definition.report_type,
            "formats": list(definition.formats or []),
            "trigger": trigger,
            "simulation_only": True,
            "external_delivery_allowed": False,
            "real_spend_allowed": False,
        },
    )
    return row


async def get_report_run(
    session: AsyncSession, actor: UserRecord, run_id: str
) -> GrowthReportRun:
    await _require(session, actor, "reports.manage")
    row = await session.scalar(
        select(GrowthReportRun).where(
            GrowthReportRun.id == run_id,
            GrowthReportRun.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise GrowthAdvancedError("report-run-not-found")
    return row


async def report_artifact(
    session: AsyncSession, actor: UserRecord, run_id: str, format_name: str
) -> tuple[bytes, str, str]:
    await _require(session, actor, "exports.create")
    row = await get_report_run(session, actor, run_id)
    entry = next(
        (
            item
            for item in list(row.artifact_manifest or [])
            if item.get("format") == format_name
        ),
        None,
    )
    if entry is None:
        raise GrowthAdvancedError("artifact-format-not-generated")
    data, media_type, filename = render_artifact(
        format_name, dict(row.data_snapshot or {})
    )
    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
        raise GrowthAdvancedError("artifact-checksum-mismatch")
    return data, media_type, filename


async def simulate_due_reports(
    session: AsyncSession, actor: UserRecord, now: datetime | None = None
) -> list[GrowthReportRun]:
    await _require(session, actor, "reports.manage")
    await _require(session, actor, "automations.manage")
    current = now or _now()
    definitions = await session.scalars(
        select(GrowthReportDefinition).where(
            GrowthReportDefinition.organization_id == actor.organization_id,
            GrowthReportDefinition.active.is_(True),
            GrowthReportDefinition.schedule_kind != "manual",
            GrowthReportDefinition.next_run_at.is_not(None),
            GrowthReportDefinition.next_run_at <= current,
        )
    )
    runs: list[GrowthReportRun] = []
    for definition in list(definitions)[:20]:
        runs.append(await run_report(session, actor, definition.id, trigger="schedule"))
    return runs


def public_report_run(row: GrowthReportRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "report_definition_id": row.report_definition_id,
        "status": row.status,
        "summary": dict(row.summary or {}),
        "artifact_manifest": list(row.artifact_manifest or []),
        "simulated": bool(row.simulated),
        "external_delivery_allowed": False,
        "generated_at": row.generated_at,
    }


def branding_preview(payload: dict[str, Any]) -> dict[str, Any]:
    brand_name = str(payload.get("brand_name") or "AIONEX AIOS").strip()[:180]
    custom_domain = _safe_domain(payload.get("custom_domain"))
    branding = dict(_safe_value(dict(payload.get("branding") or {})))
    return {
        "brand_name": brand_name or "AIONEX AIOS",
        "custom_domain": custom_domain,
        "branding": branding,
        "domain_verification_state": (
            "unverified" if custom_domain else "not_configured"
        ),
        "live_domain_allowed": False,
        "external_delivery_allowed": False,
    }


async def branding_preview_for_actor(
    session: AsyncSession, actor: UserRecord, payload: dict[str, Any]
) -> dict[str, Any]:
    await _require(session, actor, "reports.manage")
    return branding_preview(payload)
