from aios.web_dashboard_integration import (
    DashboardContract,
    DashboardManifest,
    DashboardModule,
    DashboardRequest,
    IntegrationHealthStatus,
    WebDashboardIntegrationPlatform,
)


def test_web_dashboard_integration_end_to_end() -> None:
    platform = WebDashboardIntegrationPlatform.build_default()
    contract = DashboardContract(
        contract_id="projects.v1",
        module=DashboardModule.PROJECTS,
        api_version="v1",
        route_prefix="/api/v1/projects",
        capabilities=frozenset({"projects:read"}),
    )
    platform.contracts.register(contract)
    token = platform.tokens.issue("user-1", {"projects:read"}, organization_id="org-1")
    platform.gateway.register_handler(
        "projects.v1",
        "list",
        lambda request: {"items": [{"project_id": "p-1"}], "payload": request.payload},
    )
    response = platform.gateway.dispatch(
        DashboardRequest(
            contract_id="projects.v1",
            operation="list",
            token=token.token,
            payload={"status": "active"},
        )
    )
    assert response.success is True
    assert response.data["items"][0]["project_id"] == "p-1"
    assert platform.validate()["ready"] is True


def test_manifest_and_health_validation() -> None:
    platform = WebDashboardIntegrationPlatform.build_default()
    contract = DashboardContract(
        contract_id="analytics.v1",
        module=DashboardModule.ANALYTICS,
        api_version="v1",
        route_prefix="/api/v1/analytics",
        capabilities=frozenset({"analytics:read"}),
    )
    platform.contracts.register(contract)
    manifest = DashboardManifest(
        dashboard_id="aionex-web",
        name="AIONEX Web Dashboard",
        version="1.0.0",
        entrypoint="/index.html",
        contracts=("analytics.v1",),
        required_capabilities=frozenset({"analytics:read"}),
    )
    validation = platform.manifests.validate(manifest, platform.contracts.list())
    assert validation["valid"] is True
    report = platform.health.evaluate({"gateway": True, "contracts": True, "dashboard_assets": False})
    assert report.status is IntegrationHealthStatus.DEGRADED
