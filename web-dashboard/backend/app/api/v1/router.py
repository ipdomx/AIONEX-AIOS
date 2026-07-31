"""API router configuration."""

from app.api.owner import (
    control_plane,
    final_platform_integration,
    free_tier,
    operations_integration,
    platform_integration,
    production_runtime,
    security_integration,
)
from app.api.v1.endpoints import (
    ai_agents,
    ai_providers,
    auth,
    backups,
    containers,
    dashboard,
    databases,
    final_integration,
    integration,
    knowledge,
    meetings,
    monitoring,
    notifications,
    organizations,
    permissions,
    projects,
    reports,
    roles,
    search,
    security,
    servers,
    settings,
    tasks,
    users,
    websocket,
    workflows,
    workspaces,
)
from app.core.auth import require_super_owner
from app.services.free_tier import (
    enforce_free_project_request,
    enforce_free_workspace_request,
    require_non_free_user,
)
from fastapi import APIRouter, Depends

api_router = APIRouter()

restricted = [Depends(require_non_free_user)]

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(
    users.router,
    prefix="/users",
    tags=["Users"],
    dependencies=restricted,
)
api_router.include_router(
    organizations.router,
    prefix="/organizations",
    tags=["Organizations"],
    dependencies=restricted,
)
api_router.include_router(
    workspaces.router,
    prefix="/workspaces",
    tags=["Workspaces"],
    dependencies=[Depends(enforce_free_workspace_request)],
)
api_router.include_router(
    projects.router,
    prefix="/projects",
    tags=["Projects"],
    dependencies=[Depends(enforce_free_project_request)],
)
api_router.include_router(
    ai_agents.router,
    prefix="/ai/agents",
    tags=["AI Agents"],
    dependencies=restricted,
)
api_router.include_router(
    ai_providers.router,
    prefix="/ai/providers",
    tags=["AI Providers"],
    dependencies=restricted,
)
api_router.include_router(
    workflows.router,
    prefix="/workflows",
    tags=["Workflows"],
    dependencies=restricted,
)
api_router.include_router(
    servers.router,
    prefix="/infrastructure/servers",
    tags=["Servers"],
    dependencies=restricted,
)
api_router.include_router(
    containers.router,
    prefix="/infrastructure/containers",
    tags=["Containers"],
    dependencies=restricted,
)
api_router.include_router(
    databases.router,
    prefix="/infrastructure/databases",
    tags=["Databases"],
    dependencies=restricted,
)
api_router.include_router(
    monitoring.router,
    prefix="/monitoring",
    tags=["Monitoring"],
    dependencies=restricted,
)
api_router.include_router(
    security.router,
    prefix="/security",
    tags=["Security"],
    dependencies=restricted,
)
api_router.include_router(
    tasks.router,
    prefix="/tasks",
    tags=["Tasks"],
    dependencies=restricted,
)
api_router.include_router(
    meetings.router,
    prefix="/meetings",
    tags=["Meetings"],
    dependencies=restricted,
)
api_router.include_router(
    knowledge.router,
    prefix="/knowledge",
    tags=["Knowledge"],
    dependencies=restricted,
)
api_router.include_router(
    dashboard.router,
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=restricted,
)
api_router.include_router(
    search.router,
    prefix="/search",
    tags=["Search"],
    dependencies=restricted,
)
api_router.include_router(
    notifications.router,
    prefix="/notifications",
    tags=["Notifications"],
    dependencies=restricted,
)
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])
api_router.include_router(
    roles.router,
    prefix="/roles",
    tags=["Roles"],
    dependencies=restricted,
)
api_router.include_router(
    permissions.router,
    prefix="/permissions",
    tags=["Permissions"],
    dependencies=restricted,
)
api_router.include_router(
    reports.router,
    prefix="/reports",
    tags=["Reports"],
    dependencies=restricted,
)
api_router.include_router(
    backups.router,
    prefix="/backups",
    tags=["Backup and Recovery"],
    dependencies=restricted,
)
api_router.include_router(websocket.router, prefix="/realtime", tags=["Realtime"])
api_router.include_router(
    integration.router,
    prefix="/integration",
    tags=["AIOS Integration"],
    dependencies=restricted,
)
api_router.include_router(
    final_integration.router,
    prefix="/final-integration",
    tags=["Final Integration"],
    dependencies=restricted,
)

owner_router = APIRouter(dependencies=[Depends(require_super_owner)])
owner_router.include_router(platform_integration.router)
owner_router.include_router(operations_integration.router)
owner_router.include_router(security_integration.router)
owner_router.include_router(production_runtime.router)
owner_router.include_router(final_platform_integration.router)
owner_router.include_router(free_tier.router)
owner_router.include_router(control_plane.router)
api_router.include_router(owner_router)
