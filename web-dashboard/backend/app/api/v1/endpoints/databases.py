"""Databases endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

class DatabaseResponse(BaseModel):
    id: str
    name: str
    type: str
    host: str
    port: int
    status: str
    size: float
    connections: int
    queries_per_second: int
    slow_queries: int
    backup_status: str
    last_backup: Optional[str]
    created_at: str


@router.get("", response_model=List[DatabaseResponse])
async def list_databases(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    type: Optional[str] = None,
    status: Optional[str] = None,
):
    """List all databases."""
    return [
        {
            "id": f"db-{i}",
            "name": f"db-primary-{i:02d}",
            "type": "postgresql" if i % 3 == 0 else "mysql" if i % 3 == 1 else "redis",
            "host": f"10.0.2.{i + 10}",
            "port": 5432 if i % 3 == 0 else 3306 if i % 3 == 1 else 6379,
            "status": "connected" if i % 4 != 0 else "error",
            "size": 1024.5 + i * 100,
            "connections": 45 + i * 5,
            "queries_per_second": 1200 + i * 100,
            "slow_queries": i % 10,
            "backup_status": "ok" if i % 3 != 0 else "warning",
            "last_backup": "2024-01-15T02:00:00Z",
            "created_at": "2024-01-01T00:00:00Z",
        }
        for i in range(limit)
    ]

@router.get("/{db_id}")
async def get_database(db_id: str):
    """Get database by ID."""
    return {
        "id": db_id,
        "name": "db-primary-01",
        "type": "postgresql",
        "host": "10.0.2.10",
        "port": 5432,
        "status": "connected",
        "size_mb": 2048.5,
        "connections": 67,
        "queries_per_second": 1450,
        "slow_queries": 3,
        "replication_lag_ms": 12,
        "backup_status": "ok",
        "last_backup": "2024-01-15T02:00:00Z",
        "tables": 45,
        "indexes": 120,
        "replication": {"master": "db-primary-01", "replicas": ["db-replica-01", "db-replica-02"]},
    }

@router.post("/{db_id}/backup")
async def backup_database(db_id: str):
    """Trigger database backup."""
    return {"message": "Backup started", "db_id": db_id, "job_id": "backup-123"}

@router.get("/{db_id}/queries")
async def get_slow_queries(db_id: str, limit: int = 20):
    """Get slow queries."""
    return [
        {
            "id": f"query-{i}",
            "query": f"SELECT * FROM table_{i} WHERE...",
            "duration_ms": 500 + i * 50,
            "calls": 100 + i * 10,
            "avg_time_ms": 450 + i * 20,
        }
        for i in range(limit)
    ]
