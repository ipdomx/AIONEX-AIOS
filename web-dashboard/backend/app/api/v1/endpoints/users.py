"""Users endpoints."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr
from typing import List, Optional

router = APIRouter()

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    role_id: str
    organization_id: str
    workspace_id: Optional[str] = None

class UserUpdate(BaseModel):
    name: Optional[str] = None
    role_id: Optional[str] = None
    status: Optional[str] = None
    avatar: Optional[str] = None

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    avatar: Optional[str]
    role: str
    status: str
    organization: str
    workspace: Optional[str]
    last_active: Optional[str]
    created_at: str


@router.get("", response_model=List[UserResponse])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    organization_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    """List all users with filtering and pagination."""
    return [
        {
            "id": f"user-{i}",
            "email": f"user{i}@aionex.io",
            "name": f"User {i}",
            "avatar": None,
            "role": "Engineer",
            "status": "online" if i % 3 == 0 else "offline",
            "organization": "AIONEX Corp",
            "workspace": "Engineering" if i % 2 == 0 else None,
            "last_active": "2024-01-15T10:00:00Z",
            "created_at": "2024-01-01T00:00:00Z",
        }
        for i in range(limit)
    ]

@router.post("", status_code=201)
async def create_user(data: UserCreate):
    """Create new user."""
    return {"id": "new-user-id", "message": "User created successfully"}

@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str):
    """Get user by ID."""
    return {
        "id": user_id,
        "email": "alex@aionex.io",
        "name": "Alex Chen",
        "avatar": None,
        "role": "Super Owner",
        "status": "online",
        "organization": "AIONEX Corp",
        "workspace": "Engineering",
        "last_active": "2024-01-15T10:00:00Z",
        "created_at": "2024-01-01T00:00:00Z",
    }

@router.put("/{user_id}")
async def update_user(user_id: str, data: UserUpdate):
    """Update user."""
    return {"id": user_id, "message": "User updated successfully"}

@router.delete("/{user_id}")
async def delete_user(user_id: str):
    """Delete user (soft delete)."""
    return {"message": "User deleted successfully"}

@router.get("/{user_id}/activity")
async def get_user_activity(user_id: str, limit: int = 20):
    """Get user activity log."""
    return [
        {
            "id": f"activity-{i}",
            "type": "login" if i % 4 == 0 else "action",
            "description": f"Activity {i}",
            "timestamp": "2024-01-15T10:00:00Z",
        }
        for i in range(limit)
    ]

@router.get("/{user_id}/sessions")
async def get_user_sessions(user_id: str):
    """Get active user sessions."""
    return [
        {
            "id": "session-1",
            "ip": "192.168.1.100",
            "user_agent": "Mozilla/5.0",
            "location": "Dubai, UAE",
            "created_at": "2024-01-15T08:00:00Z",
            "last_active": "2024-01-15T10:00:00Z",
            "is_current": True,
        }
    ]
