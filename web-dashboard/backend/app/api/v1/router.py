"""API router configuration."""

from app.api.owner import (
    control_plane,
    final_platform_integration,
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
from fastapi import APIRouter, Depends

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(
    organizations.router, prefix="/organizations", tags=["Organizations"]
)
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["Workspaces"])
api_router.include_router(projects.router, prefix="/projects", tags=["Projects"])
api_router.include_router(ai_agents.router, prefix="/ai/agents", tags=["AI Agents"])
api_router.include_router(
    ai_providers.router, prefix="/ai/providers", tags=["AI Providers"]
)
api_router.include_router(workflows.router, prefix="/workflows", tags=["Workflows"])
api_router.include_router(
    servers.router, prefix="/infrastructure/servers", tags=["Servers"]
)
api_router.include_router(
    containers.router, prefix="/infrastructure/containers", tags=["Containers"]
)
api_router.include_router(
    databases.router, prefix="/infrastructure/databases", tags=["Databases"]
)
api_router.include_router(monitoring.router, prefix="/monitoring", tags=["Monitoring"])
api_router.include_router(security.router, prefix="/security", tags=["Security"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
api_router.include_router(meetings.router, prefix="/meetings", tags=["Meetings"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(search.router, prefix="/search", tags=["Search"])
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["Notifications"]
)
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])
api_router.include_router(roles.router, prefix="/roles", tags=["Roles"])
api_router.include_router(
    permissions.router, prefix="/permissions", tags=["Permissions"]
)
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(
    backups.router, prefix="/backups", tags=["Backup and Recovery"]
)
api_router.include_router(websocket.router, prefix="/realtime", tags=["Realtime"])
api_router.include_router(
    integration.router, prefix="/integration", tags=["AIOS Integration"]
)
api_router.include_router(
    final_integration.router, prefix="/final-integration", tags=["Final Integration"]
)

owner_router = APIRouter(dependencies=[Depends(require_super_owner)])
owner_router.include_router(platform_integration.router)
owner_router.include_router(operations_integration.router)
owner_router.include_router(security_integration.router)
owner_router.include_router(production_runtime.router)
owner_router.include_router(final_platform_integration.router)
owner_router.include_router(control_plane.router)
api_router.include_router(owner_router)
