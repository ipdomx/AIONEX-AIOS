"""Dashboard endpoints."""

from fastapi import APIRouter

router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats():
    """Get dashboard statistics."""
    return {
        "total_users": 2847,
        "total_organizations": 156,
        "total_projects": 89,
        "total_agents": 156,
        "active_agents": 89,
        "total_workflows": 124,
        "active_workflows": 89,
        "total_servers": 42,
        "online_servers": 38,
        "total_containers": 156,
        "running_containers": 134,
        "total_databases": 18,
        "healthy_databases": 16,
        "alerts_today": 12,
        "critical_alerts": 3,
        "tasks_today": 45,
        "completed_tasks": 30,
        "meetings_today": 8,
        "cpu_usage": 64.5,
        "memory_usage": 78.2,
        "storage_usage": 45.8,
        "network_rx": 892.4,
        "network_tx": 645.2,
        "ai_cost_today": 1247.50,
        "ai_tokens_today": 2847291,
        "api_calls_today": 4567890,
        "api_errors_today": 45,
    }

@router.get("/activity")
async def get_recent_activity(limit: int = 20):
    """Get recent activity."""
    return [
        {
            "id": f"activity-{i}",
            "type": "deployment" if i % 5 == 0 else "agent" if i % 5 == 1 else "alert" if i % 5 == 2 else "user" if i % 5 == 3 else "backup",
            "title": f"Activity {i}",
            "description": f"Activity description {i}",
            "user": "Alex Chen",
            "timestamp": "2024-01-15T10:00:00Z",
        }
        for i in range(limit)
    ]

@router.get("/charts")
async def get_dashboard_charts():
    """Get dashboard chart data."""
    return {
        "cpu_usage": {
            "labels": ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"],
            "data": [45, 52, 67, 78, 65, 55],
        },
        "memory_usage": {
            "labels": ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"],
            "data": [60, 62, 70, 82, 75, 68],
        },
        "api_calls": {
            "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "data": [3200000, 3500000, 3800000, 4200000, 3900000, 2800000, 2600000],
        },
        "ai_cost": {
            "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "data": [850, 920, 1100, 1247, 980, 650, 580],
        },
    }
