"""Servers endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

class ServerCreate(BaseModel):
    name: str
    hostname: str
    ip: str
    os: Optional[str] = None
    location: Optional[str] = None
    provider: Optional[str] = None
    organization_id: str

class ServerResponse(BaseModel):
    id: str
    name: str
    hostname: str
    ip: str
    status: str
    os: Optional[str]
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    network_rx: float
    network_tx: float
    uptime: int
    location: Optional[str]
    provider: Optional[str]
    created_at: str


@router.get("", response_model=List[ServerResponse])
async def list_servers(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    """List all servers."""
    return [
        {
            "id": f"server-{i}",
            "name": f"prod-web-{i:02d}",
            "hostname": f"prod-web-{i:02d}.aionex.io",
            "ip": f"10.0.1.{i + 10}",
            "status": "online" if i % 4 != 0 else "maintenance",
            "os": "Ubuntu 22.04 LTS",
            "cpu_usage": 45.2 + i * 2,
            "memory_usage": 67.8 + i,
            "disk_usage": 34.5 + i * 0.5,
            "network_rx": 125.4 + i * 10,
            "network_tx": 89.2 + i * 5,
            "uptime": 86400 * 30 + i * 3600,
            "location": "Dubai, UAE" if i % 2 == 0 else "Frankfurt, DE",
            "provider": "AWS" if i % 2 == 0 else "Contabo",
            "created_at": "2024-01-01T00:00:00Z",
        }
        for i in range(limit)
    ]

@router.post("", status_code=201)
async def create_server(data: ServerCreate):
    """Register new server."""
    return {"id": "new-server-id", "message": "Server registered successfully"}

@router.get("/{server_id}")
async def get_server(server_id: str):
    """Get server by ID."""
    return {
        "id": server_id,
        "name": "prod-web-01",
        "hostname": "prod-web-01.aionex.io",
        "ip": "10.0.1.10",
        "status": "online",
        "os": "Ubuntu 22.04 LTS",
        "cpu": {"cores": 8, "usage": 67.5, "history": []},
        "memory": {"total_gb": 32, "used_gb": 21.6, "usage": 67.5},
        "disk": {"total_gb": 500, "used_gb": 175, "usage": 35.0},
        "network": {"rx_mbps": 145.2, "tx_mbps": 98.7},
        "uptime": 2592000,
        "location": "Dubai, UAE",
        "provider": "AWS",
        "containers": 12,
        "processes": 234,
        "services": 45,
    }

@router.delete("/{server_id}")
async def delete_server(server_id: str):
    """Remove server."""
    return {"message": "Server removed successfully"}

@router.get("/{server_id}/metrics")
async def get_server_metrics(server_id: str, hours: int = 24):
    """Get server metrics history."""
    return {
        "cpu": [{"timestamp": f"2024-01-15T{i:02d}:00:00Z", "value": 40 + i * 2} for i in range(hours)],
        "memory": [{"timestamp": f"2024-01-15T{i:02d}:00:00Z", "value": 50 + i} for i in range(hours)],
        "disk": [{"timestamp": f"2024-01-15T{i:02d}:00:00Z", "value": 30 + i * 0.5} for i in range(hours)],
    }

@router.post("/{server_id}/reboot")
async def reboot_server(server_id: str):
    """Reboot server."""
    return {"message": "Server reboot initiated", "server_id": server_id}

@router.post("/{server_id}/maintenance")
async def toggle_maintenance(server_id: str, enable: bool = True):
    """Toggle maintenance mode."""
    return {"message": f"Maintenance mode {'enabled' if enable else 'disabled'}", "server_id": server_id}
