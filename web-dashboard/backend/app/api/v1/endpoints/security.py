"""Security endpoints."""

from fastapi import APIRouter, Query
from typing import List, Optional

router = APIRouter()

@router.get("/events")
async def get_security_events(
    type: Optional[str] = None,
    user_id: Optional[str] = None,
    risk_level: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    """Get security events."""
    return [
        {
            "id": f"event-{i}",
            "timestamp": "2024-01-15T10:00:00Z",
            "type": "login" if i % 5 == 0 else "failed_login" if i % 5 == 1 else "api_call" if i % 5 == 2 else "permission_change" if i % 5 == 3 else "suspicious",
            "user_id": f"user-{i % 10}",
            "ip": f"192.168.1.{i + 10}",
            "user_agent": "Mozilla/5.0",
            "resource": "api",
            "action": "read",
            "result": "success" if i % 3 == 0 else "failure",
            "risk_score": 10 + i * 2,
            "geo": {"country": "UAE", "city": "Dubai"},
        }
        for i in range(limit)
    ]

@router.get("/threats")
async def get_threats(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Get threat intelligence."""
    return [
        {
            "id": f"threat-{i}",
            "title": f"Threat {i}",
            "description": f"Threat description {i}",
            "severity": "high" if i % 3 == 0 else "medium",
            "status": "active" if i % 2 == 0 else "mitigated",
            "source_ip": f"10.0.0.{i + 1}",
            "detected_at": "2024-01-15T10:00:00Z",
        }
        for i in range(limit)
    ]

@router.get("/sessions")
async def get_active_sessions(
    user_id: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Get active sessions."""
    return [
        {
            "id": f"session-{i}",
            "user_id": f"user-{i % 10}",
            "user_name": f"User {i % 10}",
            "ip": f"192.168.1.{i + 10}",
            "user_agent": "Mozilla/5.0",
            "location": "Dubai, UAE",
            "created_at": "2024-01-15T08:00:00Z",
            "last_active": "2024-01-15T10:00:00Z",
            "is_current": i == 0,
        }
        for i in range(limit)
    ]

@router.delete("/sessions/{session_id}")
async def terminate_session(session_id: str):
    """Terminate session."""
    return {"message": "Session terminated", "session_id": session_id}

@router.get("/policies")
async def get_policies():
    """Get security policies."""
    return [
        {"id": "policy-1", "name": "Password Policy", "status": "active", "rules": 8},
        {"id": "policy-2", "name": "MFA Policy", "status": "active", "rules": 3},
        {"id": "policy-3", "name": "IP Whitelist", "status": "active", "rules": 15},
    ]
