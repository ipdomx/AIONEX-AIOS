from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.owner import (
    approvals,
    operations,
    realtime,
    release_governance,
    runtime,
    timeline,
)
from app.core.ai_runtime import ai_runtime
from app.core.auth import UserRecord
from app.core.identity_store import identity_store
from app.core.production_runtime import production_runtime
from app.core.runtime_store import runtime_store


def _actor(role: str = "Super Owner") -> UserRecord:
    return UserRecord(
        id="owner-live-adapter",
        email="owner-live-adapter@aionex.local",
        name="Owner Live Adapter",
        role=role,
        password_hash="unused",
        organization_id="aionex-org",
        organization_name="AIONEX Corp",
        organization_plan="enterprise",
        permissions=["*"],
    )


def test_owner_live_adapter_route_contracts() -> None:
    routers = (
        runtime.router,
        operations.router,
        approvals.router,
        realtime.router,
        release_governance.router,
        timeline.router,
    )
    registered = {
        (route.path, method)
        for owner_router in routers
        for route in owner_router.routes
        for method in (getattr(route, "methods", set()) or set())
    }

    assert registered == {
        ("/owner/runtime", "GET"),
        ("/owner/operations", "POST"),
        ("/owner/approvals", "GET"),
        ("/owner/approvals/{approval_id}", "PATCH"),
        ("/owner/realtime", "GET"),
        ("/owner/releases", "GET"),
        ("/owner/releases/{candidate_id}/decision", "POST"),
        ("/owner/timeline", "GET"),
    }


def test_runtime_projection_uses_shared_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor()
    monkeypatch.setattr(
        runtime_store,
        "projects",
        {
            "project-live": {
                "id": "project-live",
                "name": "Live Project",
                "organization_id": actor.organization_id,
                "organization": actor.organization_name,
                "status": "active",
                "progress": 64,
                "created_at": "2026-07-01T00:00:00+00:00",
                "updated_at": "2026-07-02T00:00:00+00:00",
                "deleted": False,
            }
        },
    )

    payload = runtime.build_owner_runtime_snapshot(actor).model_dump(by_alias=True)

    assert payload["projects"] == [
        {
            "id": "project-live",
            "name": "Live Project",
            "organization": "AIONEX Corp",
            "status": "active",
            "progress": 64,
            "updatedAt": "2026-07-02T00:00:00+00:00",
        }
    ]
    assert any(user["id"] == actor.id for user in payload["users"])
    assert "generatedAt" in payload


@pytest.mark.asyncio
async def test_owner_project_operation_mutates_canonical_store_and_returns_audit_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor()
    monkeypatch.setattr(runtime_store, "projects", {})
    monkeypatch.setattr(
        runtime_store,
        "workspaces",
        {
            "workspace-live": {
                "id": "workspace-live",
                "name": "Live Workspace",
                "organization_id": actor.organization_id,
            }
        },
    )
    monkeypatch.setattr(runtime_store, "activities", [])
    monkeypatch.setattr(identity_store, "audit_events", [])

    result = await operations.execute_owner_operation(
        operations.OwnerOperationRequest(
            entity="project",
            operation="create",
            payload={"name": "Connected Project", "workspace_id": "workspace-live"},
        ),
        actor,
    )

    assert result.ok
    assert len(runtime_store.projects) == 1
    assert runtime_store.activities[0]["id"] == result.operation_id
    assert runtime_store.activities[0]["title"] == "Project created"


def test_owner_approval_decision_updates_live_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor()
    workflow = {
        "id": "workflow-approval-live",
        "name": "Release Approval",
        "organization_id": actor.organization_id,
        "status": "active",
        "steps": [
            {
                "id": "owner-approval",
                "name": "Owner approval",
                "type": "approval",
                "status": "pending",
            }
        ],
        "created_at": "2026-07-01T00:00:00+00:00",
        "updated_at": "2026-07-01T00:00:00+00:00",
        "deleted": False,
    }
    monkeypatch.setattr(runtime_store, "workflows", {workflow["id"]: workflow})
    monkeypatch.setattr(runtime_store, "meetings", {})
    monkeypatch.setattr(runtime_store, "projects", {})
    monkeypatch.setattr(runtime_store, "activities", [])

    listed = approvals.list_owner_approvals(actor)
    assert [item.id for item in listed] == [
        "workflow:workflow-approval-live:owner-approval"
    ]

    decided = approvals.decide_owner_approval(
        listed[0].id,
        approvals.ApprovalDecision(status="approved", reason="All gates passed"),
        actor,
    )
    assert decided.status == "approved"
    assert workflow["steps"][0]["decided_by"] == actor.id
    assert runtime_store.activities[0]["type"] == "approval"

    with pytest.raises(HTTPException) as error:
        approvals.decide_owner_approval(
            listed[0].id,
            approvals.ApprovalDecision(status="rejected", reason="Too late"),
            actor,
        )
    assert error.value.status_code == 409


def test_realtime_projection_uses_ai_runtime_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor("Owner")
    monkeypatch.setattr(
        ai_runtime,
        "agents",
        {
            "agent-live": SimpleNamespace(
                id="agent-live",
                status="idle",
                organization_id=actor.organization_id,
            )
        },
    )
    monkeypatch.setattr(
        ai_runtime,
        "jobs",
        {
            "job-live": SimpleNamespace(
                id="job-live",
                agent_id="agent-live",
                organization_id=actor.organization_id,
                status="queued",
                created_at="2026-07-01T00:00:00+00:00",
                started_at=None,
                completed_at=None,
            )
        },
    )
    monkeypatch.setattr(
        ai_runtime,
        "providers",
        {
            "provider-live": SimpleNamespace(
                organization_id=actor.organization_id,
                latency=125,
                last_used=None,
                created_at="2026-07-01T00:00:00+00:00",
            )
        },
    )
    monkeypatch.setattr(ai_runtime, "notifications", {})
    monkeypatch.setattr(
        ai_runtime,
        "hub",
        SimpleNamespace(connected_count=lambda organization_id: 3),
    )
    monkeypatch.setattr(runtime_store, "activities", [])

    payload = realtime.build_owner_realtime_snapshot(actor).model_dump(by_alias=True)
    metrics = {item["id"]: item for item in payload["metrics"]}

    assert metrics["active-workers"]["value"] == 1
    assert metrics["queued-jobs"]["value"] == 1
    assert metrics["provider-latency"]["value"] == 125
    assert metrics["connected-clients"]["value"] == 3
    assert payload["events"][0]["id"] == "ai-job:job-live"


def test_release_decision_requires_real_passed_gates_and_persists_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor()
    workflow = {
        "id": "release-live",
        "name": "Production Release",
        "version": "4.2.0",
        "environment": "production",
        "organization_id": actor.organization_id,
        "requested_by": "Release Manager",
        "status": "active",
        "steps": [
            {
                "id": "validation",
                "name": "Validation",
                "type": "validation",
                "status": "pending",
            },
            {
                "id": "owner",
                "name": "Owner approval",
                "type": "approval",
                "status": "pending",
            },
            {
                "id": "deployment",
                "name": "Production deployment",
                "type": "deployment",
                "status": "blocked",
            },
        ],
        "created_at": "2026-07-01T00:00:00+00:00",
        "updated_at": "2026-07-01T00:00:00+00:00",
        "deleted": False,
    }
    monkeypatch.setattr(runtime_store, "workflows", {workflow["id"]: workflow})
    monkeypatch.setattr(runtime_store, "projects", {})
    monkeypatch.setattr(runtime_store, "activities", [])
    monkeypatch.setattr(production_runtime, "audit_events", [])

    assert release_governance.list_release_candidates(actor)[0].status == "blocked"
    with pytest.raises(HTTPException) as error:
        release_governance.apply_release_decision(
            workflow["id"],
            release_governance.OwnerReleaseDecision(
                decision="approve",
                note="Premature approval",
            ),
            actor,
        )
    assert error.value.status_code == 409
    assert runtime_store.activities == []
    assert production_runtime.audit_events == []

    workflow["steps"][0]["status"] = "passed"
    assert release_governance.list_release_candidates(actor)[0].status == "ready"
    candidate = release_governance.apply_release_decision(
        workflow["id"],
        release_governance.OwnerReleaseDecision(
            decision="approve",
            note="Validated for production",
        ),
        actor,
    )

    assert candidate.status == "released"
    assert workflow["steps"][1]["status"] == "approved"
    assert workflow["steps"][2]["status"] == "released"
    assert runtime_store.activities[0]["type"] == "approval"
    assert production_runtime.audit_events[-1]["action"] == "release.approve"


def test_timeline_merges_real_audit_sources_with_namespaced_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor()
    monkeypatch.setattr(
        runtime_store,
        "activities",
        [
            {
                "id": "activity-live",
                "type": "project",
                "title": "Project updated",
                "description": "Live Project",
                "user_id": actor.id,
                "timestamp": "2026-07-01T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(
        identity_store,
        "audit_events",
        [
            {
                "id": "identity-live",
                "actor_user_id": actor.id,
                "action": "delete",
                "resource_type": "user",
                "resource_id": "user-live",
                "metadata": {},
                "timestamp": "2026-07-02T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(ai_runtime, "jobs", {})
    monkeypatch.setattr(ai_runtime, "notifications", {})
    monkeypatch.setattr(
        production_runtime,
        "audit_events",
        [
            {
                "id": "release-audit-live",
                "actor": actor.id,
                "action": "release.approve",
                "resource": "release-live",
                "metadata": {"note": "Approved"},
                "timestamp": "2026-07-03T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(production_runtime, "security_events", [])
    monkeypatch.setattr(production_runtime, "alerts", {})
    monkeypatch.setattr(production_runtime, "logs", [])

    payload = timeline.build_owner_timeline(actor).model_dump(by_alias=True)

    assert [event["id"] for event in payload["events"]] == [
        "production-audit:release-audit-live",
        "identity:identity-live",
        "runtime:activity-live",
    ]
    assert payload["events"][0]["category"] == "approval"
    assert payload["events"][1]["category"] == "user"
    assert payload["events"][1]["severity"] == "warning"
    assert "occurredAt" in payload["events"][0]
