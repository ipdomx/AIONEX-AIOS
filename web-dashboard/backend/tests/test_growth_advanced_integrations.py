from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import Organization, User
from app.services import growth_advanced_integrations as advanced


def _actor(org_id: str, user_id: str, email: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=email,
        name="GS10 Test",
        role="User",
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS10",
        organization_plan="test",
        permissions=[],
        status="active",
        auth_version=1,
    )


@pytest.mark.asyncio
async def test_gs10_safe_integrations_team_reports_and_exports(monkeypatch) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs10-org-{suffix}"
    user_id = f"gs10-user-{suffix}"
    email = f"gs10-{suffix}@example.invalid"
    requested_capabilities: list[str] = []

    async def allow(_session, _actor, capability):
        requested_capabilities.append(str(capability))
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(advanced.growth_access, "effective_access", allow)
    actor = _actor(org_id, user_id, email)

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS10 Test",
                slug=f"gs10-{suffix}",
                plan="test",
                status="active",
            )
        )
        session.add(
            User(
                id=user_id,
                organization_id=org_id,
                email=email,
                name="GS10 Test",
                password_hash="unused",
                status="active",
                auth_version=1,
            )
        )
        await session.commit()

        with pytest.raises(
            advanced.GrowthAdvancedError, match="raw-secret-field-forbidden"
        ):
            await advanced.create_integration(
                session,
                actor,
                {
                    "integration_type": "webhook",
                    "provider": "generic",
                    "name": "Unsafe",
                    "config": {
                        "endpoint": "https://example.com/hook",
                        "api_token": "forbidden",
                    },
                },
            )

        integration = await advanced.create_integration(
            session,
            actor,
            {
                "integration_type": "webhook",
                "provider": "generic",
                "name": f"Safe webhook {suffix}",
                "credential_ref": "secretref://vault/gs10-webhook",
                "config": {"endpoint": "https://example.com/aionex-hook"},
                "capabilities": ["report.delivery.simulation"],
            },
        )
        public = advanced.public_integration(integration)
        assert public["credential_configured"] is True
        assert "credential_ref" not in public
        assert public["external_delivery_allowed"] is False
        assert public["live_provider_call"] is False

        evidence = await advanced.simulate_integration(session, actor, integration.id)
        assert evidence["simulation_only"] is True
        assert evidence["provider_call_allowed"] is False
        assert evidence["external_delivery_allowed"] is False
        assert evidence["message_send_allowed"] is False
        assert evidence["webhook_delivery_allowed"] is False
        assert evidence["raw_secret_persisted"] is False

        assignment = await advanced.upsert_team_assignment(
            session,
            actor,
            {
                "user_id": user_id,
                "scope_type": "report",
                "scope_id": "*",
                "role_key": "approver",
                "permissions": ["read", "approve", "export"],
                "approval_required": True,
            },
        )
        assignment_public = advanced.public_team_assignment(assignment)
        assert assignment_public["role_key"] == "approver"
        assert assignment_public["approval_required"] is True
        assert assignment_public["active"] is True

        assignments = await advanced.list_team_assignments(session, actor)
        assert [row.id for row in assignments] == [assignment.id]
        routing = await advanced.simulate_team_routing(session, actor, "report", "*")
        assert routing["matched_assignments"] == 1
        assert routing["recommended_user_id"] == user_id
        assert routing["recommended_role"] == "approver"
        assert routing["assignment_applied"] is False
        assert routing["provider_call_allowed"] is False
        assert routing["external_mutation_allowed"] is False

        definition = await advanced.create_report_definition(
            session,
            actor,
            {
                "name": f"Executive {suffix}",
                "report_type": "executive",
                "formats": ["json", "csv", "xlsx", "pdf"],
                "schedule_kind": "manual",
                "timezone": "Asia/Dubai",
                "brand_name": "AIONEX",
                "custom_domain": "reports.example.com",
                "branding": {"logo_ref": "resource://brand/logo"},
            },
        )
        definition_public = advanced.public_report_definition(definition)
        assert definition_public["external_delivery_allowed"] is False
        assert definition_public["live_domain_allowed"] is False
        assert definition_public["domain_verification_state"] == "unverified"
        assert definition_public["custom_domain"] == "reports.example.com"

        definitions = await advanced.list_report_definitions(session, actor)
        assert definition.id in {row.id for row in definitions}

        run = await advanced.run_report(session, actor, definition.id)
        assert run.simulated is True
        assert run.external_delivery_allowed is False
        assert run.summary["integrations"] == 1
        assert run.summary["active_team_assignments"] == 1
        assert run.summary["real_spend_allowed"] is False
        assert run.summary["external_delivery_allowed"] is False
        assert run.data_snapshot["privacy"]["aggregate_only"] is True
        assert run.data_snapshot["privacy"]["raw_credentials_exported"] is False
        assert run.data_snapshot["privacy"]["lead_contact_pii_exported"] is False
        assert run.data_snapshot["safety"]["external_delivery_allowed"] is False
        assert run.data_snapshot["safety"]["live_provider_call"] is False
        assert run.data_snapshot["safety"]["message_send_allowed"] is False
        assert run.data_snapshot["safety"]["real_spend_allowed"] is False
        assert "credential_ref" not in json.dumps(run.data_snapshot).lower()

        manifest = {item["format"]: item for item in run.artifact_manifest}
        assert set(manifest) == {"json", "csv", "xlsx", "pdf"}
        signatures = {
            "json": b"{",
            "csv": b"external_delivery_allowed",
            "xlsx": b"PK",
            "pdf": b"%PDF-1.4",
        }
        for format_name, signature in signatures.items():
            data1, media_type1, filename1 = advanced.render_artifact(
                format_name, dict(run.data_snapshot)
            )
            data2, media_type2, filename2 = advanced.render_artifact(
                format_name, dict(run.data_snapshot)
            )
            assert data1 == data2
            assert data1.startswith(signature)
            assert media_type1 == media_type2
            assert filename1 == filename2
            assert filename1.endswith(f".{format_name}")
            assert hashlib.sha256(data1).hexdigest() == manifest[format_name]["sha256"]
            assert manifest[format_name]["local_generation_only"] is True
            assert manifest[format_name]["external_delivery_allowed"] is False

            downloaded, downloaded_type, downloaded_name = (
                await advanced.report_artifact(session, actor, run.id, format_name)
            )
            assert downloaded == data1
            assert downloaded_type == media_type1
            assert downloaded_name == filename1

        scheduled = await advanced.create_report_definition(
            session,
            actor,
            {
                "name": f"Daily Provider Health {suffix}",
                "report_type": "provider_health",
                "formats": ["json"],
                "schedule_kind": "daily",
                "timezone": "Asia/Dubai",
            },
        )
        assert scheduled.next_run_at is not None
        due_runs = await advanced.simulate_due_reports(
            session, actor, now=scheduled.next_run_at + timedelta(seconds=1)
        )
        assert len(due_runs) == 1
        assert due_runs[0].simulated is True
        assert due_runs[0].external_delivery_allowed is False

        preview = await advanced.branding_preview_for_actor(
            session,
            actor,
            {
                "brand_name": "AIONEX White Label",
                "custom_domain": "brand.example.com",
                "branding": {"logo_ref": "resource://brand/logo"},
            },
        )
        assert preview["domain_verification_state"] == "unverified"
        assert preview["live_domain_allowed"] is False
        assert preview["external_delivery_allowed"] is False

        assert "integrations.manage" in requested_capabilities
        assert "teams.manage" in requested_capabilities
        assert "reports.manage" in requested_capabilities
        assert "exports.create" in requested_capabilities
        assert "automations.manage" in requested_capabilities
        await session.rollback()


def test_gs10_rejects_private_webhooks_queries_and_bad_custom_domains() -> None:
    with pytest.raises(
        advanced.GrowthAdvancedError, match="webhook-private-host-forbidden"
    ):
        advanced._validate_webhook({"endpoint": "https://127.0.0.1/hook"})

    with pytest.raises(
        advanced.GrowthAdvancedError,
        match="webhook-credentials-query-fragment-forbidden",
    ):
        advanced._validate_webhook({"endpoint": "https://example.com/hook?x=1"})

    with pytest.raises(advanced.GrowthAdvancedError, match="invalid-custom-domain"):
        advanced._safe_domain("https://reports.example.com/path")

    snapshot = {
        "name": "Deterministic",
        "report_type": "executive",
        "summary": {"integrations": 1},
        "privacy": {"aggregate_only": True},
        "safety": {"external_delivery_allowed": False},
    }
    first, _, _ = advanced.render_artifact("xlsx", snapshot)
    second, _, _ = advanced.render_artifact("xlsx", snapshot)
    assert first == second


def test_gs10_backend_routes_are_registered() -> None:
    from app.api.v1.endpoints import growth_advanced_integrations as endpoint

    paths = {route.path for route in endpoint.router.routes}
    assert "/integrations" in paths
    assert "/team-assignments" in paths
    assert "/reports" in paths
    assert "/report-runs/{run_id}" in paths
    assert "/report-runs/{run_id}/artifact/{format_name}" in paths
