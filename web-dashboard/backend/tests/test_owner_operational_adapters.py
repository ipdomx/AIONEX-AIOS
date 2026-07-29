from __future__ import annotations

from fastapi import HTTPException
from starlette.requests import Request

from app.api.owner import (
    compliance_runtime,
    executive_bi,
    finalization,
    licensing,
    notification_runtime,
)
from app.core.ai_runtime import ai_runtime
from app.core.auth import UserRecord
from main import app


def _owner() -> UserRecord:
    return UserRecord(
        id="owner-adapter-test",
        email="owner-adapter@aionex.local",
        name="Owner Adapter Test",
        role="Super Owner",
        password_hash="unused",
        organization_id="aionex-org",
        organization_name="AIONEX",
        organization_plan="enterprise",
        permissions=["*"],
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/api/v1/owner/finalization",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 50000),
        }
    )


def test_owner_operational_adapter_route_contracts() -> None:
    routers = (
        compliance_runtime.router,
        executive_bi.router,
        licensing.router,
        notification_runtime.router,
        finalization.router,
    )
    registered = {
        (route.path, method)
        for router in routers
        for route in router.routes
        for method in (getattr(route, "methods", set()) or set())
    }
    assert registered == {
        ("/owner/compliance-controls", "GET"),
        ("/owner/compliance-controls/{control_id}/attest", "POST"),
        ("/owner/executive", "GET"),
        ("/owner/licenses", "GET"),
        ("/owner/licenses/{license_id}", "PATCH"),
        ("/owner/notification-rules", "GET"),
        ("/owner/notification-rules/{rule_id}", "PATCH"),
        ("/owner/finalization", "GET"),
    }


def test_executive_and_licensing_models_match_frontend_aliases() -> None:
    actor = _owner()
    executive_payload = executive_bi.build_executive_snapshot(actor).model_dump(
        by_alias=True
    )
    assert "generatedAt" in executive_payload
    assert executive_payload["metrics"]
    assert all(metric["trend"] == 0 for metric in executive_payload["metrics"])

    license_payloads = [
        record.model_dump(by_alias=True)
        for record in licensing.build_license_records(actor)
    ]
    assert license_payloads
    assert {"activeSeats", "expiresAt", "monthlyValue"}.issubset(license_payloads[0])


def test_compliance_and_finalization_use_live_contract_evidence() -> None:
    request = _request()
    controls = compliance_runtime.build_compliance_controls(request)
    integration = next(
        control for control in controls if control.id == "integration-contracts"
    )
    assert integration.evidence > 0
    assert integration.status == "compliant"
    assert "updatedAt" in integration.model_dump(by_alias=True)

    snapshot = finalization.build_finalization_snapshot(request)
    payload = snapshot.model_dump(by_alias=True)
    assert "generatedAt" in payload
    assert {
        "integration",
        "security",
        "performance",
        "reliability",
        "usability",
    } == {check["category"] for check in payload["checks"]}
    performance = next(
        check for check in payload["checks"] if check["id"] == "performance-evidence"
    )
    assert performance["status"] == "warning"
    route_protection = next(
        check for check in payload["checks"] if check["id"] == "owner-route-protection"
    )
    assert route_protection["status"] == "passed"
    navigation = next(
        check for check in payload["checks"] if check["id"] == "owner-navigation"
    )
    assert navigation["status"] == "passed"


def test_notification_rules_project_only_observed_runtime_events() -> None:
    actor = _owner()
    notification = ai_runtime.add_notification(
        organization_id=actor.organization_id,
        user_id=None,
        type="adapter.contract.observed",
        title="Observed adapter contract",
        message="Used to verify the projection.",
        severity="warning",
    )
    try:
        rules = notification_runtime.build_notification_rules(actor)
        rule = next(item for item in rules if item.id == "adapter.contract.observed")
        payload = rule.model_dump(by_alias=True)
        assert payload["channels"] == ["in_app"]
        assert payload["severity"] == "warning"
        assert "updatedAt" in payload
    finally:
        ai_runtime.notifications.pop(notification["id"], None)


def test_notification_rule_update_does_not_report_fake_success() -> None:
    actor = _owner()
    notification = ai_runtime.add_notification(
        organization_id=actor.organization_id,
        user_id=None,
        type="adapter.contract.immutable",
        title="Immutable adapter contract",
        message="Used to verify unsupported updates.",
    )
    try:
        update = notification_runtime.NotificationRuleUpdate(enabled=False)
        try:
            notification_runtime.update_notification_rule(
                "adapter.contract.immutable",
                update,
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("Unsupported rule updates must not report success")
    finally:
        ai_runtime.notifications.pop(notification["id"], None)
