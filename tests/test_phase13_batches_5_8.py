from datetime import date

from aios.api_gateway.realtime import RealtimeEvent, RealtimeHub
from aios.api_gateway.request_pipeline import GatewayRequest, GatewayResponse, RequestPipeline
from aios.api_gateway.versioning import ApiVersion, ApiVersionRegistry
from aios.api_gateway.web_dashboard import DashboardModule, WebDashboardService


def test_request_pipeline_adds_request_id() -> None:
    pipeline = RequestPipeline(lambda request: GatewayResponse(status_code=200, body=request.path))
    response = pipeline.execute(
        GatewayRequest(
            request_id="req-1",
            method="GET",
            path="/v1/projects",
            principal_id="owner-1",
        )
    )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-1"


def test_api_version_registry_rejects_sunset_versions() -> None:
    registry = ApiVersionRegistry()
    registry.register(
        ApiVersion(
            name="v1",
            released_on=date(2025, 1, 1),
            deprecated_on=date(2026, 1, 1),
            sunset_on=date(2026, 6, 1),
        ),
        default=True,
    )

    try:
        registry.resolve("v1", today=date(2026, 7, 1))
    except RuntimeError:
        pass
    else:
        raise AssertionError("sunset API versions must be rejected")


def test_realtime_hub_isolates_owner_events() -> None:
    hub = RealtimeHub()
    hub.publish(
        RealtimeEvent(
            event_id="e-1",
            topic="projects",
            owner_id="owner-1",
            payload={"state": "active"},
        )
    )
    hub.publish(
        RealtimeEvent(
            event_id="e-2",
            topic="projects",
            owner_id="owner-2",
            payload={"state": "paused"},
        )
    )
    events = hub.read(owner_id="owner-1", topics=["projects"])
    assert [event.event_id for event in events] == ["e-1"]


def test_dashboard_manifest_filters_by_scope_and_enabled_state() -> None:
    service = WebDashboardService()
    service.register(
        DashboardModule(
            module_id="projects",
            title="Projects",
            route="/projects",
            required_scope="projects:read",
        )
    )
    service.register(
        DashboardModule(
            module_id="finance",
            title="Finance",
            route="/finance",
            required_scope="finance:read",
        )
    )
    service.set_enabled("finance", False)

    manifest = service.manifest_for("owner-1", {"projects:read", "finance:read"})
    assert [module.module_id for module in manifest.modules] == ["projects"]
