"""Containers endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

class ContainerResponse(BaseModel):
    id: str
    name: str
    image: str
    status: str
    server: str
    cpu: float
    memory: int
    restart_count: int
    health: str
    created_at: str


@router.get("", response_model=List[ContainerResponse])
async def list_containers(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    server_id: Optional[str] = None,
):
    """List all containers."""
    return [
        {
            "id": f"container-{i}",
            "name": f"app-{i}",
            "image": f"aionex/app:v{i}.0",
            "status": "running" if i % 3 != 0 else "stopped",
            "server": f"prod-web-{i % 6:02d}",
            "cpu": 12.5 + i * 0.5,
            "memory": 256 + i * 32,
            "restart_count": i % 5,
            "health": "healthy" if i % 4 != 0 else "unhealthy",
            "created_at": "2024-01-01T00:00:00Z",
        }
        for i in range(limit)
    ]

@router.get("/{container_id}")
async def get_container(container_id: str):
    """Get container by ID."""
    return {
        "id": container_id,
        "name": "app-api",
        "image": "aionex/api:latest",
        "status": "running",
        "server": "prod-web-01",
        "cpu": 15.2,
        "memory": 512,
        "memory_limit": 1024,
        "ports": [{"host": 8080, "container": 80, "protocol": "tcp"}],
        "volumes": [{"host": "/data", "container": "/app/data", "mode": "rw"}],
        "env": {"NODE_ENV": "production", "PORT": "80"},
        "logs": "Container logs...",
        "restart_count": 2,
        "health": "healthy",
    }

@router.post("/{container_id}/start")
async def start_container(container_id: str):
    """Start container."""
    return {"message": "Container started", "container_id": container_id}

@router.post("/{container_id}/stop")
async def stop_container(container_id: str):
    """Stop container."""
    return {"message": "Container stopped", "container_id": container_id}

@router.post("/{container_id}/restart")
async def restart_container(container_id: str):
    """Restart container."""
    return {"message": "Container restarted", "container_id": container_id}

@router.get("/{container_id}/logs")
async def get_container_logs(container_id: str, tail: int = 100):
    """Get container logs."""
    return {"logs": [f"Log line {i}" for i in range(tail)]}
