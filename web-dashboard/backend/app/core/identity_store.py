"""In-memory identity, organization, role, permission, and audit store.

This store is the batch-one runtime foundation. It centralizes identity state so
API endpoints no longer return mock payloads. The interface is intentionally
small and can later be backed by PostgreSQL without changing endpoint contracts.
"""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PermissionRecord:
    id: str
    key: str
    name: str
    description: str
    category: str


@dataclass
class RoleRecord:
    id: str
    name: str
    description: str
    organization_id: str | None
    permissions: list[str] = field(default_factory=list)
    is_system: bool = False
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class OrganizationRecord:
    id: str
    name: str
    slug: str
    plan: str = "enterprise"
    status: str = "active"
    owner_user_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class IdentityUserRecord:
    id: str
    email: str
    name: str
    role_id: str
    organization_id: str
    password_hash: str
    status: str = "active"
    avatar: str | None = None
    workspace_id: str | None = None
    last_active: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    deleted_at: str | None = None


class IdentityStore:
    def __init__(self) -> None:
        self.permissions: dict[str, PermissionRecord] = {}
        self.roles: dict[str, RoleRecord] = {}
        self.organizations: dict[str, OrganizationRecord] = {}
        self.users: dict[str, IdentityUserRecord] = {}
        self.audit_events: list[dict[str, Any]] = []
        self.sessions: dict[str, list[dict[str, Any]]] = {}
        self._bootstrap()

    def _bootstrap(self) -> None:
        permission_specs = [
            ("users:read", "Read Users", "View users and user details", "identity"),
            ("users:write", "Manage Users", "Create, update, and deactivate users", "identity"),
            ("organizations:read", "Read Organizations", "View organizations", "organization"),
            ("organizations:write", "Manage Organizations", "Create and update organizations", "organization"),
            ("roles:read", "Read Roles", "View roles and assignments", "access"),
            ("roles:write", "Manage Roles", "Create and update roles", "access"),
            ("permissions:read", "Read Permissions", "View permissions", "access"),
            ("permissions:write", "Manage Permissions", "Update permission assignments", "access"),
            ("projects:read", "Read Projects", "View projects", "projects"),
            ("projects:write", "Manage Projects", "Create and update projects", "projects"),
            ("profile:read", "Read Profile", "View own profile", "identity"),
            ("audit:read", "Read Audit", "View access and identity audit trail", "security"),
        ]
        for key, name, description, category in permission_specs:
            self.permissions[key] = PermissionRecord(
                id=f"perm-{key.replace(':', '-')}", key=key, name=name, description=description, category=category
            )

        self.organizations["aionex-org"] = OrganizationRecord(
            id="aionex-org", name="AIONEX Corp", slug="aionex", owner_user_id="owner-1"
        )
        all_permissions = sorted(self.permissions)
        system_roles = [
            ("role-super-owner", "Super Owner", "Full platform ownership", all_permissions),
            ("role-owner", "Owner", "Organization owner", all_permissions),
            ("role-manager", "Manager", "Organization and team management", [
                "users:read", "users:write", "organizations:read", "roles:read", "permissions:read", "projects:read", "projects:write", "profile:read", "audit:read"
            ]),
            ("role-engineer", "Engineer", "Project engineering role", ["users:read", "projects:read", "projects:write", "profile:read"]),
            ("role-viewer", "Viewer", "Read-only organization role", ["users:read", "organizations:read", "roles:read", "permissions:read", "projects:read", "profile:read"]),
        ]
        for role_id, name, description, permissions in system_roles:
            self.roles[role_id] = RoleRecord(
                id=role_id,
                name=name,
                description=description,
                organization_id=None,
                permissions=permissions,
                is_system=True,
            )

    def record_audit(self, actor_user_id: str, action: str, resource_type: str, resource_id: str, metadata: dict[str, Any] | None = None) -> None:
        self.audit_events.insert(0, {
            "id": secrets.token_urlsafe(10),
            "actor_user_id": actor_user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "metadata": metadata or {},
            "timestamp": utc_now(),
        })

    def role_by_name(self, name: str) -> RoleRecord | None:
        normalized = name.strip().lower()
        return next((role for role in self.roles.values() if role.name.lower() == normalized), None)

    def get_role(self, role_id: str) -> RoleRecord:
        role = self.roles.get(role_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")
        return role

    def get_organization(self, organization_id: str) -> OrganizationRecord:
        organization = self.organizations.get(organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        return organization

    def get_user(self, user_id: str) -> IdentityUserRecord:
        user = self.users.get(user_id)
        if user is None or user.deleted_at is not None:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    def find_user_by_email(self, email: str) -> IdentityUserRecord | None:
        normalized = email.strip().lower()
        return next((user for user in self.users.values() if user.email == normalized and user.deleted_at is None), None)

    def serialize_permission(self, permission: PermissionRecord) -> dict[str, Any]:
        return asdict(permission)

    def serialize_role(self, role: RoleRecord) -> dict[str, Any]:
        payload = asdict(role)
        payload["user_count"] = sum(1 for user in self.users.values() if user.role_id == role.id and user.deleted_at is None)
        return payload

    def serialize_organization(self, organization: OrganizationRecord) -> dict[str, Any]:
        payload = asdict(organization)
        payload["member_count"] = sum(1 for user in self.users.values() if user.organization_id == organization.id and user.deleted_at is None)
        payload["role_count"] = sum(1 for role in self.roles.values() if role.organization_id in (None, organization.id))
        return payload

    def serialize_user(self, user: IdentityUserRecord) -> dict[str, Any]:
        role = self.get_role(user.role_id)
        organization = self.get_organization(user.organization_id)
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "avatar": user.avatar,
            "role": role.name,
            "role_id": role.id,
            "permissions": role.permissions,
            "status": user.status,
            "organization": organization.name,
            "organization_id": organization.id,
            "workspace": user.workspace_id,
            "workspace_id": user.workspace_id,
            "last_active": user.last_active,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }


identity_store = IdentityStore()
