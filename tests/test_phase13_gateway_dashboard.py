from aios.dashboard.owner_api import OwnerDashboardApi, OwnerDashboardSnapshot
from aios.gateway.api_keys import ApiKeyService
from aios.gateway.models import GatewayRequest, GatewayRoute, HttpMethod
from aios.gateway.router import ApiGatewayRouter


def test_gateway_authorization_and_rate_limit() -> None:
    router = ApiGatewayRouter()
    router.register(
        GatewayRoute(
            route_id="route-1",
            path="/v1/projects",
            method=HttpMethod.GET,
            target_service="projects",
            required_scopes={"projects:read"},
            rate_limit_per_minute=1,
        )
    )

    denied = router.evaluate(
        GatewayRequest(
            request_id="req-1",
            path="/v1/projects",
            method=HttpMethod.GET,
            principal_id="user-1",
            scopes=frozenset(),
        )
    )
    assert denied.status_code == 403

    allowed = router.evaluate(
        GatewayRequest(
            request_id="req-2",
            path="/v1/projects",
            method=HttpMethod.GET,
            principal_id="user-1",
            scopes=frozenset({"projects:read"}),
        )
    )
    assert allowed.allowed is True
    assert allowed.target_service == "projects"

    limited = router.evaluate(
        GatewayRequest(
            request_id="req-3",
            path="/v1/projects",
            method=HttpMethod.GET,
            principal_id="user-1",
            scopes=frozenset({"projects:read"}),
        )
    )
    assert limited.status_code == 429


def test_api_key_issue_authenticate_and_revoke() -> None:
    service = ApiKeyService()
    record, secret = service.issue(
        key_id="key-1",
        owner_id="owner-1",
        name="automation",
        scopes={"projects:read"},
    )
    assert service.authenticate(record.key_id, secret).owner_id == "owner-1"
    service.revoke(record.key_id, "owner-1")

    try:
        service.authenticate(record.key_id, secret)
    except PermissionError:
        pass
    else:
        raise AssertionError("revoked key must not authenticate")


def test_owner_dashboard_snapshot_scope() -> None:
    api = OwnerDashboardApi()
    snapshot = api.publish(
        OwnerDashboardSnapshot(
            owner_id="owner-1",
            active_projects=5,
            pending_approvals=2,
            open_incidents=1,
            active_workers=8,
            queued_tasks=12,
            monthly_cost=250.0,
        )
    )

    assert api.get("owner-1") == snapshot
