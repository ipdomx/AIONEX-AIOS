from aios.web_integration import (
    DashboardCapability,
    DashboardManifest,
    DashboardRequest,
    DashboardResponse,
    DashboardRoute,
    WebIntegrationFoundation,
)


def test_web_integration_end_to_end() -> None:
    platform = WebIntegrationFoundation.build_default(secret="test-secret")
    manifest = DashboardManifest(
        dashboard_id="main-dashboard",
        name="AIONEX Web Dashboard",
        version="1.0.0",
        routes=(
            DashboardRoute(
                route_id="projects",
                path="/projects",
                capabilities=frozenset({DashboardCapability.PROJECTS_READ}),
                methods=frozenset({"GET"}),
            ),
        ),
    )
    platform.registry.register(manifest)
    token = platform.tokens.issue(
        subject_id="owner-1",
        dashboard_id="main-dashboard",
        capabilities={DashboardCapability.PROJECTS_READ},
    )
    session = platform.sessions.create(
        subject_id="owner-1",
        dashboard_id="main-dashboard",
        token_id=token.token_id,
    )
    platform.gateway.register_handler(
        "main-dashboard",
        "projects",
        lambda request: DashboardResponse(
            status_code=200,
            data={"projects": ["project-1"], "subject": token.subject_id},
            correlation_id=request.correlation_id,
        ),
    )

    response = platform.gateway.dispatch(
        DashboardRequest(
            dashboard_id="main-dashboard",
            route_id="projects",
            method="GET",
            session_id=session.session_id,
            correlation_id="corr-1",
        )
    )

    assert response.status_code == 200
    assert response.data["projects"] == ["project-1"]
    assert response.correlation_id == "corr-1"
    assert platform.registry.validate("main-dashboard")["ready"] is True
    assert platform.validate()["ready"] is True


def test_web_integration_rejects_missing_capability() -> None:
    platform = WebIntegrationFoundation.build_default(secret="test-secret")
    platform.registry.register(
        DashboardManifest(
            dashboard_id="main-dashboard",
            name="AIONEX Web Dashboard",
            version="1.0.0",
            routes=(
                DashboardRoute(
                    route_id="owner-control",
                    path="/owner-control",
                    capabilities=frozenset({DashboardCapability.OWNER_CONTROL}),
                ),
            ),
        )
    )
    token = platform.tokens.issue(
        subject_id="user-1",
        dashboard_id="main-dashboard",
        capabilities={DashboardCapability.PROJECTS_READ},
    )
    session = platform.sessions.create("user-1", "main-dashboard", token.token_id)
    platform.gateway.register_handler(
        "main-dashboard",
        "owner-control",
        lambda request: DashboardResponse(status_code=200, data={"ok": True}),
    )

    try:
        platform.gateway.dispatch(
            DashboardRequest(
                dashboard_id="main-dashboard",
                route_id="owner-control",
                method="GET",
                session_id=session.session_id,
            )
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("missing capability must be rejected")
