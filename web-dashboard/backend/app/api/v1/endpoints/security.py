"""Security, audit and session endpoints."""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.core.production_runtime import production_runtime

router = APIRouter()


@router.get("/events")
async def get_security_events(type: Optional[str] = None, user_id: Optional[str] = None, risk_level: Optional[str] = None, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    items = list(reversed(production_runtime.security_events))
    if type:
        items = [item for item in items if item["type"] == type]
    if user_id:
        items = [item for item in items if item.get("user_id") == user_id]
    if risk_level:
        items = [item for item in items if item["risk_level"] == risk_level]
    return items[skip:skip + limit]


@router.post("/events")
async def create_security_event(event_type: str, risk_score: int = Query(..., ge=0, le=100), result: str = "detected", user_id: str | None = None, ip: str | None = None):
    return production_runtime.security_event(event_type, risk_score, result, user_id, ip)


@router.get("/threats")
async def get_threats(severity: Optional[str] = None, status: Optional[str] = None, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    items = []
    for event in reversed(production_runtime.security_events):
        if event["risk_score"] < 60:
            continue
        item = {"id": event["id"], "title": f"Security threat: {event['type']}", "description": f"Risk score {event['risk_score']}", "severity": event["risk_level"], "status": "active" if event["result"] != "mitigated" else "mitigated", "source_ip": event.get("ip"), "detected_at": event["timestamp"]}
        items.append(item)
    if severity:
        items = [item for item in items if item["severity"] == severity]
    if status:
        items = [item for item in items if item["status"] == status]
    return items[skip:skip + limit]


@router.get("/audit")
async def get_audit_events(action: str | None = None, actor: str | None = None, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    items = list(reversed(production_runtime.audit_events))
    if action:
        items = [item for item in items if item["action"] == action]
    if actor:
        items = [item for item in items if item["actor"] == actor]
    return items[skip:skip + limit]


@router.post("/audit")
async def create_audit_event(actor: str, action: str, resource: str):
    return production_runtime.audit(actor, action, resource)


@router.get("/policies")
async def get_policies():
    return [
        {"id": "password-policy", "name": "Password Policy", "status": "active", "rules": {"minimum_length": 12, "rotation_required": True}},
        {"id": "mfa-policy", "name": "MFA Policy", "status": "active", "rules": {"owners_required": True, "admins_required": True}},
        {"id": "session-policy", "name": "Session Policy", "status": "active", "rules": {"access_minutes": 30, "refresh_days": 7}},
        {"id": "audit-policy", "name": "Audit Policy", "status": "active", "rules": {"retention_days": 365, "immutable": True}},
    ]


@router.delete("/sessions/{session_id}")
async def terminate_session(session_id: str):
    production_runtime.audit("operator", "session.terminate", session_id)
    return {"message": "Session termination recorded", "session_id": session_id}
