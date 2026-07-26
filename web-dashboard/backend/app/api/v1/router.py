"""API router configuration."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    users,
    organizations,
    workspaces,
    projects,
    ai_agents,
    ai_providers,
    workflows,
    servers,
    containers,
    databases,
    monitoring,
    security,
    tasks,
    meetings,
    knowledge,
    dashboard,
    search,
    notifications,
    settings,
    roles,
    permissions,
    websocket,
    integration,
    reports,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["Organizations"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["Workspaces"])
api_router.include_router(projects.router, prefix="/projects", tags=["Projects"])
api_router.include_router(ai_agents.router, prefix="/ai/agents", tags=["AI Agents"])
api_router.include_router(ai_providers.router, prefix="/ai/providers", tags=["AI Providers"])
api_router.include_router(workflows.router, prefix="/workflows", tags=["Workflows"])
api_router.include_router(servers.router, prefix="/infrastructure/servers", tags=["Servers"])
api_router.include_router(containers.router, prefix="/infrastructure/containers", tags=["Containers"])
api_router.include_router(databases.router, prefix="/infrastructure/databases", tags=["Databases"])
api_router.include_router(monitoring.router, prefix="/monitoring", tags=["Monitoring"])
api_router.include_router(security.router, prefix="/security", tags=["Security"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
api_router.include_router(meetings.router, prefix="/meetings", tags=["Meetings"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(search.router, prefix="/search", tags=["Search"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])
api_router.include_router(roles.router, prefix="/roles", tags=["Roles"])
api_router.include_router(permissions.router, prefix="/permissions", tags=["Permissions"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(integration.router, prefix="/integration", tags=["AIOS Integration"])
