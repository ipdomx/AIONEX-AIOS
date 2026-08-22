"""Consolidated relational schema for dashboard runtime persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(200), unique=True, nullable=False, index=True
    )
    plan: Mapped[str] = mapped_column(String(50), default="enterprise", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False, index=True
    )


class Role(Base, TimestampMixin):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_role_org_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False, index=True
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(
        String(160), unique=True, nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[str] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_org_status", "organization_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[str | None] = mapped_column(
        ForeignKey("roles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    avatar: Mapped[str | None] = mapped_column(Text)
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshSession(Base, TimestampMixin):
    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)


class ExternalIdentity(Base, TimestampMixin):
    """A verified identity owned by an external authentication provider."""

    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_external_identity_subject"),
        UniqueConstraint(
            "user_id", "provider", name="uq_external_identity_user_provider"
        ),
        Index("ix_external_identity_user_provider", "user_id", "provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    provider_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasskeyCredential(Base, TimestampMixin):
    """A WebAuthn public-key credential. Private keys never leave the device."""

    __tablename__ = "passkey_credentials"
    __table_args__ = (
        UniqueConstraint("credential_id", name="uq_passkey_credential_id"),
        Index("ix_passkey_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    transports: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    aaguid: Mapped[str | None] = mapped_column(String(64))
    device_type: Mapped[str | None] = mapped_column(String(32))
    backed_up: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    nickname: Mapped[str] = mapped_column(
        String(120), default="Passkey", nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordResetToken(Base, TimestampMixin):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_password_reset_user_expiry", "user_id", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[str | None] = mapped_column(String(64))
    delivery_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )
    delivery_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class UserMFA(Base, TimestampMixin):
    __tablename__ = "user_mfa"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    backup_code_hashes: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_workspace_org_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class Team(Base, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_team_org_slug"),
        Index("ix_teams_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class TeamMembership(Base, TimestampMixin):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_membership"),
        Index("ix_team_memberships_user_team", "user_id", "team_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    membership_role: Mapped[str] = mapped_column(
        String(32), default="member", nullable=False
    )


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),
        Index(
            "ix_projects_org_status_priority", "organization_id", "status", "priority"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    slug: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="planning", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    risk: Mapped[str] = mapped_column(String(32), default="normal", nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), default="not_requested", nullable=False)
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_org_project_status", "organization_id", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    assignee_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="todo", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), default="not_requested", nullable=False)
    rework_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    trigger: Mapped[str] = mapped_column(String(80), default="manual", nullable=False)
    steps: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Meeting(Base, TimestampMixin):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    organizer_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    approved_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(String(300))
    attendee_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(40), default="standard", nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC", nullable=False)
    agenda: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="ready", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)
    generated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    format: Mapped[str] = mapped_column(String(32), default="json", nullable=False)
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class AIProvider(Base, TimestampMixin):
    __tablename__ = "ai_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default="configured", nullable=False
    )
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class AIAgent(Base, TimestampMixin):
    __tablename__ = "ai_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="idle", nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_org_status_created", "organization_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_agents.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectExecution(Base, TimestampMixin):
    """Durable PostgreSQL-backed project execution requested by a user."""

    __tablename__ = "project_executions"
    __table_args__ = (
        Index(
            "ix_project_executions_org_status_created",
            "organization_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_project_executions_project_created",
            "project_id",
            "created_at",
        ),
        Index(
            "ix_project_executions_dispatch_queue",
            "status",
            "resource_class",
            "priority_rank",
            "available_at",
            "created_at",
        ),
        Index(
            "ix_project_executions_lease_recovery",
            "status",
            "lease_expires_at",
        ),
        Index(
            "uq_project_executions_active_project",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(32), default="planning", nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="openai", nullable=False)
    model: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(
        String(32), default="queued", nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(64), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    external_processing_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    budget_cap_usd: Mapped[float] = mapped_column(Float, nullable=False)
    calculated_cost_usd: Mapped[float | None] = mapped_column(Float)
    requests_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retries_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved: Mapped[bool | None] = mapped_column(Boolean)
    readiness_score: Mapped[float | None] = mapped_column(Float)
    result_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_path: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_owner: Mapped[str | None] = mapped_column(String(160), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resource_class: Mapped[str] = mapped_column(
        String(64), default="project-build-cpu", nullable=False, index=True
    )
    priority_rank: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), default="not_requested", nullable=False)
    rework_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectExecutionWorkerNode(Base, TimestampMixin):
    """Durable live project-worker membership and saturation heartbeat."""

    __tablename__ = "project_execution_workers"
    __table_args__ = (
        Index("ix_project_execution_workers_status_heartbeat", "status", "last_heartbeat_at"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    resource_classes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="online", nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True
    )


class ProjectAIRoutePlanRecord(Base, TimestampMixin):
    """Durable prompt-free Project AI route plan for one execution version."""

    __tablename__ = "project_ai_route_plans"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "plan_version",
            name="uq_project_ai_route_plan_execution_version",
        ),
        Index(
            "ix_project_ai_route_plans_org_status_created",
            "organization_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_project_ai_route_plans_project_created",
            "project_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("project_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False, index=True)
    policy: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    total_primary_estimated_microusd: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )


class ProjectAIRouteTaskRecord(Base, TimestampMixin):
    """Prompt-free durable task route and validated candidate snapshot."""

    __tablename__ = "project_ai_route_tasks"
    __table_args__ = (
        UniqueConstraint("plan_id", "task_id", name="uq_project_ai_route_task_plan_task"),
        Index(
            "ix_project_ai_route_tasks_org_status",
            "organization_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("project_ai_route_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    task: Mapped[str] = mapped_column(String(80), nullable=False)
    primary_provider_id: Mapped[str] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    primary_provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_model: Mapped[str] = mapped_column(String(160), nullable=False)
    candidates: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    estimated_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False, index=True)
    selected_provider_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="RESTRICT"), index=True
    )
    selected_provider_type: Mapped[str | None] = mapped_column(String(64))
    selected_model: Mapped[str | None] = mapped_column(String(160))
    evidence_ref: Mapped[str | None] = mapped_column(Text)


class ProjectAIRouteAttemptRecord(Base, TimestampMixin):
    """Durable provider-attempt accounting/evidence without prompts or credentials."""

    __tablename__ = "project_ai_route_attempts"
    __table_args__ = (
        UniqueConstraint(
            "task_route_id",
            "attempt_index",
            name="uq_project_ai_route_attempt_task_index",
        ),
        Index(
            "ix_project_ai_route_attempts_org_status_created",
            "organization_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_project_ai_route_attempts_provider_status",
            "provider_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    task_route_id: Mapped[str] = mapped_column(
        ForeignKey("project_ai_route_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("project_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="reserved", nullable=False, index=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    estimated_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reserved_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    actual_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    evidence_ref: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectAIExecutionBudget(Base, TimestampMixin):
    """Durable micro-USD reservation/spend authority shared by Project Workers."""

    __tablename__ = "project_ai_execution_budgets"
    __table_args__ = (
        Index("ix_project_ai_execution_budgets_org", "organization_id"),
    )

    execution_id: Mapped[str] = mapped_column(
        ForeignKey("project_executions.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    limit_microusd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    spent_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class BillingPlan(Base, TimestampMixin):
    __tablename__ = "billing_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), default="inactive", nullable=False, index=True
    )
    default_currency: Mapped[str] = mapped_column(
        String(3), default="USD", nullable=False
    )
    limits: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    entitlements: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    metering: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class BillingPrice(Base, TimestampMixin):
    __tablename__ = "billing_prices"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "period_code",
            "currency",
            name="uq_billing_price_plan_period_currency",
        ),
        Index("ix_billing_prices_plan_enabled", "plan_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("billing_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_code: Mapped[str] = mapped_column(String(80), nullable=False)
    months: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    compare_at_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="none", nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255))
    price_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class BillingAccount(Base, TimestampMixin):
    __tablename__ = "billing_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_plans.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False, index=True
    )
    licensed_seats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    provider_customers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    limits: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    entitlements: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(Text)


class BillingSubscription(Base, TimestampMixin):
    __tablename__ = "billing_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_reference",
            name="uq_billing_subscription_provider_external",
        ),
        Index("ix_billing_subscriptions_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("billing_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    price_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_prices.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, index=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )


class BillingCheckoutSession(Base, TimestampMixin):
    __tablename__ = "billing_checkout_sessions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_billing_checkout_idempotency"),
        UniqueConstraint(
            "provider",
            "external_reference",
            name="uq_billing_checkout_provider_external",
        ),
        Index("ix_billing_checkout_org_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("billing_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    price_id: Mapped[str] = mapped_column(
        ForeignKey("billing_prices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, index=True
    )
    checkout_url: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    coupon_code: Mapped[str | None] = mapped_column(String(80))
    billing_country: Mapped[str | None] = mapped_column(String(2))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class BillingInvoice(Base, TimestampMixin):
    __tablename__ = "billing_invoices"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_reference",
            name="uq_billing_invoice_provider_external",
        ),
        Index("ix_billing_invoices_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(
        String(40), default="internal", nullable=False
    )
    external_reference: Mapped[str | None] = mapped_column(String(255))
    number: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    discount_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_paid_minor: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )
    amount_refunded_minor: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )
    line_items: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invoice_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class BillingTransaction(Base, TimestampMixin):
    __tablename__ = "billing_transactions"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_reference",
            name="uq_billing_transaction_provider_external",
        ),
        UniqueConstraint("idempotency_key", name="uq_billing_transaction_idempotency"),
        Index("ix_billing_transactions_org_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    invoice_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_invoices.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(255))
    transaction_type: Mapped[str] = mapped_column(
        String(40), default="payment", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, index=True
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    transaction_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingPaymentMethod(Base, TimestampMixin):
    __tablename__ = "billing_payment_methods"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_reference", name="uq_billing_payment_method_external"
        ),
        Index("ix_billing_payment_methods_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    method_type: Mapped[str] = mapped_column(String(40), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(40))
    last4: Mapped[str | None] = mapped_column(String(4))
    expiry_month: Mapped[int | None] = mapped_column(Integer)
    expiry_year: Mapped[int | None] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class BillingRefund(Base, TimestampMixin):
    __tablename__ = "billing_refunds"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_billing_refund_idempotency"),
        UniqueConstraint(
            "provider", "external_reference", name="uq_billing_refund_provider_external"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("billing_transactions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_invoices.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(255))
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refund_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class BillingWebhookEvent(Base, TimestampMixin):
    __tablename__ = "billing_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_event_id", name="uq_billing_webhook_provider_event"
        ),
        Index("ix_billing_webhooks_status_received", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="received", nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingCoupon(Base, TimestampMixin):
    __tablename__ = "billing_coupons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True
    )
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)
    percent_off_basis_points: Mapped[int | None] = mapped_column(Integer)
    amount_off_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    redeemed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    coupon_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class BillingCouponRedemption(Base, TimestampMixin):
    __tablename__ = "billing_coupon_redemptions"
    __table_args__ = (
        UniqueConstraint(
            "coupon_id", "checkout_session_id", name="uq_billing_coupon_checkout"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    coupon_id: Mapped[str] = mapped_column(
        ForeignKey("billing_coupons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checkout_session_id: Mapped[str] = mapped_column(
        ForeignKey("billing_checkout_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class BillingTaxRate(Base, TimestampMixin):
    __tablename__ = "billing_tax_rates"
    __table_args__ = (
        UniqueConstraint(
            "country_code", "region_code", "code", name="uq_billing_tax_scope_code"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    region_code: Mapped[str | None] = mapped_column(String(80))
    percentage_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    inclusive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BillingUsageRecord(Base, TimestampMixin):
    __tablename__ = "billing_usage_records"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "metric", "period_start", name="uq_billing_usage_period"
        ),
        Index(
            "ix_billing_usage_org_period",
            "organization_id",
            "period_start",
            "period_end",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    included_quantity: Mapped[int | None] = mapped_column(BigInteger)
    billable_quantity: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )
    charge_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class BillingWallet(Base, TimestampMixin):
    __tablename__ = "billing_wallets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    balance_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class BillingWalletEntry(Base, TimestampMixin):
    __tablename__ = "billing_wallet_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_billing_wallet_entry_idempotency"),
        Index("ix_billing_wallet_entries_wallet_created", "wallet_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    wallet_id: Mapped[str] = mapped_column(
        ForeignKey("billing_wallets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(80))
    reference_id: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    entry_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class BillingLicense(Base, TimestampMixin):
    __tablename__ = "billing_licenses"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_billing_license_key_hash"),
        Index("ix_billing_licenses_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_plans.id", ondelete="SET NULL"), index=True
    )
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    seats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    license_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MobileStoreProduct(Base, TimestampMixin):
    __tablename__ = "mobile_store_products"
    __table_args__ = (
        UniqueConstraint("store", "product_id", "base_plan_id", "offer_id", name="uq_mobile_store_product_ref"),
        Index("ix_mobile_store_products_plan_status", "plan_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    plan_id: Mapped[str] = mapped_column(ForeignKey("billing_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    price_id: Mapped[str] = mapped_column(ForeignKey("billing_prices.id", ondelete="CASCADE"), nullable=False, index=True)
    store: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    base_plan_id: Mapped[str | None] = mapped_column(String(255))
    offer_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="inactive", nullable=False, index=True)
    store_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MobileStorePurchase(Base, TimestampMixin):
    __tablename__ = "mobile_store_purchases"
    __table_args__ = (
        UniqueConstraint("store", "external_transaction_id", name="uq_mobile_store_purchase_transaction"),
        Index("ix_mobile_store_purchases_org_status", "organization_id", "status"),
        Index("ix_mobile_store_purchases_user_store", "user_id", "store"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("mobile_store_products.id", ondelete="RESTRICT"), nullable=False, index=True)
    store: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    external_transaction_id: Mapped[str | None] = mapped_column(String(255))
    original_transaction_id: Mapped[str | None] = mapped_column(String(255), index=True)
    purchase_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    purchase_token_ciphertext: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending_verification", nullable=False, index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_renewing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MobileStoreEvent(Base, TimestampMixin):
    __tablename__ = "mobile_store_events"
    __table_args__ = (
        UniqueConstraint("store", "external_event_id", name="uq_mobile_store_event_external"),
        Index("ix_mobile_store_events_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    store: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="received", nullable=False, index=True)
    event_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingReconciliationRun(Base, TimestampMixin):
    __tablename__ = "billing_reconciliation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, index=True
    )
    requested_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_recipient_read", "recipient_id", "read_at"),
        Index("ix_notifications_org_event_created", "organization_id", "event_key", "created_at"),
        UniqueConstraint("organization_id", "dedupe_key", name="uq_notifications_org_dedupe"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="system", nullable=False, index=True)
    event_key: Mapped[str] = mapped_column(String(160), default="notification.created", nullable=False, index=True)
    audience: Mapped[str] = mapped_column(String(40), default="user", nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="info", nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(80))
    source_id: Mapped[str | None] = mapped_column(String(160))
    correlation_id: Mapped[str | None] = mapped_column(String(160), index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommunicationEndpoint(Base, TimestampMixin):
    __tablename__ = "communication_endpoints"
    __table_args__ = (
        UniqueConstraint("user_id", "channel", "address_hash", name="uq_communication_endpoint"),
        Index("ix_communication_endpoints_user_channel", "user_id", "channel", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    address_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    address_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(120), default="Primary", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    endpoint_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class NotificationPreference(Base, TimestampMixin):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_notification_preference_user_category"),
        Index("ix_notification_preferences_user", "user_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(80), default="*", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["in_app"], nullable=False)
    minimum_severity: Mapped[str] = mapped_column(String(32), default="info", nullable=False)
    quiet_hours_start: Mapped[str | None] = mapped_column(String(5))
    quiet_hours_end: Mapped[str | None] = mapped_column(String(5))
    timezone: Mapped[str] = mapped_column(String(80), default="UTC", nullable=False)
    digest_mode: Mapped[str] = mapped_column(String(32), default="immediate", nullable=False)


class EscalationPolicy(Base, TimestampMixin):
    __tablename__ = "escalation_policies"
    __table_args__ = (
        UniqueConstraint("code", name="uq_escalation_policies_code"),
        Index("ix_escalation_policies_enabled", "enabled", "severity_threshold"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity_threshold: Mapped[str] = mapped_column(String(32), default="warning", nullable=False)
    steps: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class NotificationRule(Base, TimestampMixin):
    __tablename__ = "notification_rules"
    __table_args__ = (
        UniqueConstraint("code", name="uq_notification_rules_code"),
        Index("ix_notification_rules_event_enabled", "event_pattern", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    escalation_policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("escalation_policies.id", ondelete="SET NULL"), index=True
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_pattern: Mapped[str] = mapped_column(String(160), nullable=False)
    audience: Mapped[str] = mapped_column(String(40), default="user", nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["in_app"], nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="info", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    title_template: Mapped[str | None] = mapped_column(String(240))
    message_template: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class NotificationDelivery(Base, TimestampMixin):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notification_delivery_idempotency"),
        Index("ix_notification_delivery_due", "status", "next_attempt_at"),
        Index("ix_notification_delivery_notification", "notification_id", "channel"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notification_id: Mapped[str] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint_id: Mapped[str | None] = mapped_column(
        ForeignKey("communication_endpoints.id", ondelete="SET NULL"), index=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    delivery_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class NotificationDeliveryAttempt(Base):
    __tablename__ = "notification_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("delivery_id", "attempt_number", name="uq_notification_delivery_attempt"),
        Index("ix_notification_delivery_attempts_delivery", "delivery_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    delivery_id: Mapped[str] = mapped_column(
        ForeignKey("notification_deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(120))
    response_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportRequest(Base, TimestampMixin):
    __tablename__ = "support_requests"
    __table_args__ = (
        Index("ix_support_requests_org_status", "organization_id", "status", "updated_at"),
        Index("ix_support_requests_requester", "requester_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requester_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assigned_to_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="general", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="normal", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False, index=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class SupportMessage(Base):
    __tablename__ = "support_messages"
    __table_args__ = (Index("ix_support_messages_request_created", "support_request_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    support_request_id: Mapped[str] = mapped_column(
        ForeignKey("support_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    visibility: Mapped[str] = mapped_column(String(32), default="requester", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_org_status", "organization_id", "status", "created_at"),
        Index("ix_approval_requests_target", "target_type", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requester_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    risk: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    required_role: Mapped[str] = mapped_column(String(120), default="Owner", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    __table_args__ = (Index("ix_approval_decisions_request_created", "approval_request_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    approval_request_id: Mapped[str] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    decision_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class GovernanceBody(Base, TimestampMixin):
    __tablename__ = "governance_bodies"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_governance_body_org_slug"),
        Index("ix_governance_bodies_org_kind", "organization_id", "kind", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("governance_bodies.id", ondelete="SET NULL"), index=True
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    charter: Mapped[str | None] = mapped_column(Text)
    jurisdiction: Mapped[str | None] = mapped_column(String(240))
    quorum: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    body_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class GovernanceMembership(Base, TimestampMixin):
    __tablename__ = "governance_memberships"
    __table_args__ = (
        UniqueConstraint("body_id", "user_id", name="uq_governance_membership"),
        Index("ix_governance_memberships_body_status", "body_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    body_id: Mapped[str] = mapped_column(
        ForeignKey("governance_bodies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(80), default="member", nullable=False)
    voting_weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class GovernancePolicy(Base, TimestampMixin):
    __tablename__ = "governance_policies"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_governance_policy_org_code"),
        Index("ix_governance_policies_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body_id: Mapped[str | None] = mapped_column(
        ForeignKey("governance_bodies.id", ondelete="SET NULL"), index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(120), default="organization", nullable=False)
    enforcement: Mapped[str] = mapped_column(String(32), default="mandatory", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    policy: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GovernanceDecision(Base, TimestampMixin):
    __tablename__ = "governance_decisions"
    __table_args__ = (Index("ix_governance_decisions_org_status", "organization_id", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body_id: Mapped[str | None] = mapped_column(
        ForeignKey("governance_bodies.id", ondelete="SET NULL"), index=True
    )
    policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("governance_policies.id", ondelete="SET NULL"), index=True
    )
    meeting_id: Mapped[str | None] = mapped_column(
        ForeignKey("meetings.id", ondelete="SET NULL"), index=True
    )
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    decision: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GovernanceVote(Base):
    __tablename__ = "governance_votes"
    __table_args__ = (
        UniqueConstraint("decision_id", "voter_id", name="uq_governance_vote"),
        Index("ix_governance_votes_decision", "decision_id", "vote"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("governance_decisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voter_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vote: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class MeetingAttendance(Base, TimestampMixin):
    __tablename__ = "meeting_attendance"
    __table_args__ = (
        UniqueConstraint("meeting_id", "user_id", name="uq_meeting_attendance"),
        Index("ix_meeting_attendance_meeting_status", "meeting_id", "response_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    response_status: Mapped[str] = mapped_column(String(32), default="invited", nullable=False)
    response_note: Mapped[str | None] = mapped_column(Text)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MeetingMinutes(Base, TimestampMixin):
    __tablename__ = "meeting_minutes"
    __table_args__ = (UniqueConstraint("meeting_id", name="uq_meeting_minutes_meeting"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    published_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    summary: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    decisions: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    action_items: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_org_created", "organization_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(120))
    resource_id: Mapped[str | None] = mapped_column(String(160))
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True
    )


class MetricSample(Base):
    __tablename__ = "metric_samples"
    __table_args__ = (
        Index("ix_metric_name_resource_time", "name", "resource", "timestamp"),
        Index("ix_metric_samples_timestamp", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    resource: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    labels: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    assigned_to_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    acknowledged_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackupRecord(Base, TimestampMixin):
    __tablename__ = "backup_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    scope: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, index=True
    )
    location: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DisasterRecoveryRun(Base, TimestampMixin):
    __tablename__ = "disaster_recovery_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    region: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GrowthCampaignBrief(Base, TimestampMixin):
    __tablename__ = "growth_campaign_briefs"
    __table_args__ = (
        Index("ix_growth_campaign_briefs_org_status_created", "organization_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    objective: Mapped[str] = mapped_column(String(80), nullable=False)
    product_summary: Mapped[str] = mapped_column(Text, nullable=False)
    target_markets: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    audience_hypotheses: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    competitor_hypotheses: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    offer_hypotheses: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    channel_hypotheses: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    budget_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    evidence: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthCampaignSimulation(Base, TimestampMixin):
    __tablename__ = "growth_campaign_simulations"
    __table_args__ = (
        Index("ix_growth_campaign_simulations_brief_created", "brief_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    brief_id: Mapped[str] = mapped_column(ForeignKey("growth_campaign_briefs.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    scenario: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_reach_min: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_reach_max: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_clicks_min: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_clicks_max: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_conversions_min: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_conversions_max: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_cpa_minor: Mapped[int | None] = mapped_column(BigInteger)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    assumptions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    real_spend_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GrowthPaidCampaign(Base, TimestampMixin):
    __tablename__ = "growth_paid_campaigns"
    __table_args__ = (
        Index("ix_growth_paid_campaigns_org_status_created", "organization_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    brief_id: Mapped[str | None] = mapped_column(ForeignKey("growth_campaign_briefs.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    objective: Mapped[str] = mapped_column(String(80), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    total_budget_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    daily_budget_cap_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    simulated_spend_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    approval_status: Mapped[str] = mapped_column(String(32), default="not_requested", nullable=False)
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_loss_policy: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    campaign_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    real_spend_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    live_provider_call: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    live_campaign_mutation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    automatic_budget_increase_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthPaidAdSet(Base, TimestampMixin):
    __tablename__ = "growth_paid_ad_sets"
    __table_args__ = (
        Index("ix_growth_paid_ad_sets_campaign_status", "campaign_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("growth_paid_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    audience: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    placements: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    bid_strategy: Mapped[str] = mapped_column(String(48), default="lowest_cost", nullable=False)
    daily_budget_cap_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    simulated_spend_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthPaidCreative(Base, TimestampMixin):
    __tablename__ = "growth_paid_creatives"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("growth_paid_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    format: Mapped[str] = mapped_column(String(40), nullable=False)
    headline: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    media_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    destination_url: Mapped[str | None] = mapped_column(Text)
    utm: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(32), default="not_requested", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthPaidAd(Base, TimestampMixin):
    __tablename__ = "growth_paid_ads"
    __table_args__ = (
        UniqueConstraint("ad_set_id", "creative_id", name="uq_growth_paid_ad_target_creative"),
        Index("ix_growth_paid_ads_campaign_status", "campaign_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("growth_paid_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    ad_set_id: Mapped[str] = mapped_column(ForeignKey("growth_paid_ad_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    creative_id: Mapped[str] = mapped_column(ForeignKey("growth_paid_creatives.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    simulated_impressions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    simulated_clicks: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    simulated_conversions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    simulated_spend_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    simulated_revenue_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthPaidLiveExecution(Base, TimestampMixin):
    __tablename__ = "growth_paid_live_executions"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "plan_digest",
            name="uq_growth_paid_live_execution_campaign_plan",
        ),
        Index(
            "ix_growth_paid_live_executions_org_status_created",
            "organization_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_growth_paid_live_executions_pilot_status",
            "pilot_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("growth_paid_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pilot_id: Mapped[str] = mapped_column(
        ForeignKey("growth_controlled_pilots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), default="meta", nullable=False)
    scope_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    creative_identity_ref: Mapped[str] = mapped_column(String(96), nullable=False)
    plan_version: Mapped[str] = mapped_column(String(80), nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="prepared", nullable=False, index=True
    )
    authorized_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_review_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    provider_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spend_executed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    automatic_execution_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthPaidLiveExecutionStep(Base, TimestampMixin):
    __tablename__ = "growth_paid_live_execution_steps"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "step_key",
            name="uq_growth_paid_live_execution_step_key",
        ),
        UniqueConstraint(
            "execution_id",
            "step_order",
            name="uq_growth_paid_live_execution_step_order",
        ),
        Index(
            "ix_growth_paid_live_execution_steps_execution_status_order",
            "execution_id",
            "status",
            "step_order",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("growth_paid_live_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(36))
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, index=True
    )
    request_digest: Mapped[str | None] = mapped_column(String(64))
    provider_object_id: Mapped[str | None] = mapped_column(String(64))
    provider_object_ref: Mapped[str | None] = mapped_column(String(96))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_call_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    provider_call_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_error_code: Mapped[str | None] = mapped_column(String(160))
    manual_review_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class GrowthPaidExperiment(Base, TimestampMixin):
    __tablename__ = "growth_paid_experiments"
    __table_args__ = (
        Index("ix_growth_paid_experiments_campaign_status", "campaign_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("growth_paid_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    variant_ad_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allocation: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    primary_metric: Mapped[str] = mapped_column(String(48), default="conversion_rate", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class GrowthPaidLaunchSimulation(Base, TimestampMixin):
    __tablename__ = "growth_paid_launch_simulations"
    __table_args__ = (
        Index("ix_growth_paid_launch_simulations_campaign_created", "campaign_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("growth_paid_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    seed: Mapped[str] = mapped_column(String(64), nullable=False)
    simulated_days: Mapped[int] = mapped_column(Integer, nullable=False)
    simulated_spend_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    real_spend_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    live_provider_call: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    live_campaign_mutation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GrowthPaidDecision(Base, TimestampMixin):
    __tablename__ = "growth_paid_decisions"
    __table_args__ = (
        Index("ix_growth_paid_decisions_campaign_created", "campaign_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("growth_paid_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("growth_paid_launch_simulations.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    automatic_execution_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    real_spend_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GrowthSocialAccount(Base, TimestampMixin):
    """Durable managed social account registry. Provider credentials never live here."""

    __tablename__ = "growth_social_accounts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "external_account_id",
            name="uq_growth_social_account_provider_external",
        ),
        Index(
            "ix_growth_social_accounts_org_provider_status",
            "organization_id",
            "provider",
            "status",
        ),
        Index("ix_growth_social_accounts_token_expiry", "token_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    account_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    public_handle: Mapped[str | None] = mapped_column(String(255))
    credential_ref: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    health_state: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    health_reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthSocialProviderCapability(Base, TimestampMixin):
    """Provider capability verification state; GS-03 cannot mark capabilities live-verified."""

    __tablename__ = "growth_social_provider_capabilities"
    __table_args__ = (
        UniqueConstraint(
            "provider", "capability", name="uq_growth_social_provider_capability"
        ),
        Index(
            "ix_growth_social_provider_capability_state",
            "provider",
            "verification_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    verification_state: Mapped[str] = mapped_column(
        String(32), default="unverified", nullable=False
    )
    mutation_class: Mapped[str] = mapped_column(String(24), default="read", nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    simulated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthContentItem(Base, TimestampMixin):
    __tablename__ = "growth_content_items"
    __table_args__ = (
        Index("ix_growth_content_items_org_status_created", "organization_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    base_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    link_url: Mapped[str | None] = mapped_column(Text)
    media_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    approval_status: Mapped[str] = mapped_column(String(32), default="not_requested", nullable=False)
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str | None] = mapped_column(Text)
    recycle_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GrowthContentVariant(Base, TimestampMixin):
    __tablename__ = "growth_content_variants"
    __table_args__ = (
        UniqueConstraint("content_id", "provider", "account_id", name="uq_growth_content_variant_target"),
        Index("ix_growth_content_variants_content_provider", "content_id", "provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    content_id: Mapped[str] = mapped_column(ForeignKey("growth_content_items.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("growth_social_accounts.id", ondelete="SET NULL"), index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    link_url: Mapped[str | None] = mapped_column(Text)
    media_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    mentions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    platform_overrides: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ready", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthContentSchedule(Base, TimestampMixin):
    __tablename__ = "growth_content_schedules"
    __table_args__ = (
        Index("ix_growth_content_schedules_due", "status", "scheduled_for", "priority"),
        Index("ix_growth_content_schedules_content_created", "content_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    content_id: Mapped[str] = mapped_column(ForeignKey("growth_content_items.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id: Mapped[str] = mapped_column(ForeignKey("growth_content_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("growth_social_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC", nullable=False)
    recurrence: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recycle_of_schedule_id: Mapped[str | None] = mapped_column(ForeignKey("growth_content_schedules.id", ondelete="SET NULL"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    simulated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GrowthContentPublishSimulation(Base, TimestampMixin):
    __tablename__ = "growth_content_publish_simulations"
    __table_args__ = (
        Index("ix_growth_content_publish_schedule_created", "schedule_id", "created_at"),
        Index("ix_growth_content_publish_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_id: Mapped[str] = mapped_column(ForeignKey("growth_content_schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    content_id: Mapped[str] = mapped_column(ForeignKey("growth_content_items.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id: Mapped[str] = mapped_column(ForeignKey("growth_content_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("growth_social_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    preview: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    utm_url: Mapped[str | None] = mapped_column(Text)
    live_publish_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    simulated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class GrowthPerformanceObservation(Base, TimestampMixin):
    __tablename__ = "growth_performance_observations"
    __table_args__ = (
        Index("ix_growth_observations_org_subject_period", "organization_id", "subject_type", "subject_id", "period_end"),
        Index("ix_growth_observations_org_source_created", "organization_id", "source", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    recorded_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(48), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    impressions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reach: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    engagements: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    conversions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    spend_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    revenue_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    followers_delta: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    extra_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    sample_quality: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class GrowthLearningEntry(Base, TimestampMixin):
    __tablename__ = "growth_learning_entries"
    __table_args__ = (
        UniqueConstraint("observation_id", name="uq_growth_learning_observation"),
        Index("ix_growth_learning_org_fingerprint_created", "organization_id", "fingerprint", "created_at"),
        Index("ix_growth_learning_org_outcome_created", "organization_id", "outcome", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    observation_id: Mapped[str] = mapped_column(ForeignKey("growth_performance_observations.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(48), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(160), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    normalized_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurrence_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthOptimizationRecommendation(Base, TimestampMixin):
    __tablename__ = "growth_optimization_recommendations"
    __table_args__ = (
        UniqueConstraint("learning_entry_id", name="uq_growth_recommendation_learning"),
        Index("ix_growth_recommendations_org_action_created", "organization_id", "action", "created_at"),
        Index("ix_growth_recommendations_org_eligible_created", "organization_id", "replay_eligible", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    learning_entry_id: Mapped[str] = mapped_column(ForeignKey("growth_learning_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(48), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(160), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    auto_optimization_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_replay_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GrowthLeadRecord(Base, TimestampMixin):
    __tablename__ = "growth_lead_records"
    __table_args__ = (
        UniqueConstraint("organization_id", "dedupe_fingerprint", name="uq_growth_lead_org_fingerprint"),
        Index("ix_growth_leads_org_status_created", "organization_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(240))
    email_normalized: Mapped[str | None] = mapped_column(String(320), index=True)
    phone_normalized: Mapped[str | None] = mapped_column(String(64), index=True)
    company_name: Mapped[str | None] = mapped_column(String(240))
    country_code: Mapped[str | None] = mapped_column(String(2))
    dedupe_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class GrowthLeadProvenance(Base, TimestampMixin):
    __tablename__ = "growth_lead_provenance"
    __table_args__ = (Index("ix_growth_lead_provenance_lead_created", "lead_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("growth_lead_records.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    source_ref: Mapped[str | None] = mapped_column(String(500))
    collection_method: Mapped[str] = mapped_column(String(64), nullable=False)
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class GrowthLeadConsent(Base, TimestampMixin):
    __tablename__ = "growth_lead_consents"
    __table_args__ = (
        Index("ix_growth_lead_consents_lead_status", "lead_id", "status"),
        UniqueConstraint("lead_id", "purpose", "lawful_basis", name="uq_growth_lead_consent_basis"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("growth_lead_records.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    lawful_basis: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class GrowthLeadSuppression(Base, TimestampMixin):
    __tablename__ = "growth_lead_suppressions"
    __table_args__ = (
        UniqueConstraint("organization_id", "lead_id", "channel", name="uq_growth_lead_suppression_channel"),
        Index("ix_growth_lead_suppressions_org_channel", "organization_id", "channel"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("growth_lead_records.id", ondelete="CASCADE"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    suppressed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)



class GrowthInboxThread(Base, TimestampMixin):
    __tablename__ = "growth_inbox_threads"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "account_id", "external_thread_ref", name="uq_growth_inbox_thread_external"),
        Index("ix_growth_inbox_threads_org_status_updated", "organization_id", "status", "updated_at"),
        Index("ix_growth_inbox_threads_org_assignee_updated", "organization_id", "assigned_to_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("growth_social_accounts.id", ondelete="SET NULL"), index=True)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("growth_lead_records.id", ondelete="SET NULL"), index=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    external_thread_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    thread_type: Mapped[str] = mapped_column(String(32), nullable=False)
    participant_ref: Mapped[str | None] = mapped_column(String(240))
    participant_name: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False, index=True)
    unread_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    starred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assigned_to_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    sentiment: Mapped[str] = mapped_column(String(24), default="neutral", nullable=False)
    spam_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class GrowthInboxMessage(Base, TimestampMixin):
    __tablename__ = "growth_inbox_messages"
    __table_args__ = (
        UniqueConstraint("thread_id", "external_message_ref", name="uq_growth_inbox_message_external"),
        Index("ix_growth_inbox_messages_thread_created", "thread_id", "created_at"),
        Index("ix_growth_inbox_messages_org_direction_created", "organization_id", "direction", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("growth_inbox_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    external_message_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    author_ref: Mapped[str | None] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    sentiment: Mapped[str] = mapped_column(String(24), default="neutral", nullable=False)
    spam_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    provider_event: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class GrowthInboxNote(Base, TimestampMixin):
    __tablename__ = "growth_inbox_notes"
    __table_args__ = (Index("ix_growth_inbox_notes_thread_created", "thread_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("growth_inbox_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class GrowthQuickReplyDraft(Base, TimestampMixin):
    __tablename__ = "growth_quick_reply_drafts"
    __table_args__ = (Index("ix_growth_quick_replies_thread_status_created", "thread_id", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("growth_inbox_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    template_key: Mapped[str | None] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    ai_suggested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    external_send_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class OwnerControlRecord(Base, TimestampMixin):
    """Durable owner-managed configuration for dashboard control surfaces."""

    __tablename__ = "owner_control_records"
    __table_args__ = (
        UniqueConstraint(
            "domain",
            "resource_id",
            name="uq_owner_control_domain_resource",
        ),
        Index("ix_owner_control_domain_status", "domain", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    domain: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class OwnerCommandRecord(Base):
    """Append-only audit record for every mutating owner dashboard command."""

    __tablename__ = "owner_command_records"
    __table_args__ = (
        Index("ix_owner_command_domain_created", "domain", "created_at"),
        Index("ix_owner_command_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False)
    request: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Phase 29F — project delivery, workforce, academy, and knowledge persistence.

class ProjectMembership(Base, TimestampMixin):
    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("project_id", "member_key", name="uq_project_membership_key"),
        Index("ix_project_memberships_org_project_status", "organization_id", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    workforce_member_id: Mapped[str | None] = mapped_column(ForeignKey("workforce_members.id", ondelete="SET NULL"), index=True)
    member_key: Mapped[str] = mapped_column(String(160), nullable=False)
    member_type: Mapped[str] = mapped_column(String(32), default="human", nullable=False)
    role: Mapped[str] = mapped_column(String(120), default="contributor", nullable=False)
    allocation_percent: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class ProjectEvent(Base):
    __tablename__ = "project_events"
    __table_args__ = (
        Index("ix_project_events_project_created", "project_id", "created_at"),
        Index("ix_project_events_org_type_created", "organization_id", "event_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[str | None] = mapped_column(String(500))
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)


class TaskComment(Base):
    __tablename__ = "task_comments"
    __table_args__ = (Index("ix_task_comments_task_created", "task_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    workforce_member_id: Mapped[str | None] = mapped_column(ForeignKey("workforce_members.id", ondelete="SET NULL"), index=True)
    visibility: Mapped[str] = mapped_column(String(32), default="organization", nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_workflow_created", "workflow_id", "created_at"),
        Index("ix_workflow_runs_org_status_created", "organization_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkforceMember(Base, TimestampMixin):
    __tablename__ = "workforce_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "worker_key", name="uq_workforce_member_org_key"),
        Index("ix_workforce_members_org_status_kind", "organization_id", "status", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("workforce_members.id", ondelete="SET NULL"), index=True)
    worker_key: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="human", nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str] = mapped_column(String(120), default="Unassigned", nullable=False)
    ministry: Mapped[str | None] = mapped_column(String(160))
    grade: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    certifications: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    restrictions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    provider_neutral: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    profile_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkforceAssignment(Base, TimestampMixin):
    __tablename__ = "workforce_assignments"
    __table_args__ = (
        Index("ix_workforce_assignments_worker_status", "worker_id", "status", "created_at"),
        Index("ix_workforce_assignments_project_status", "project_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workforce_members.id", ondelete="RESTRICT"), nullable=False, index=True)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("workforce_members.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    required_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="assigned", nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    risk: Mapped[str] = mapped_column(String(32), default="normal", nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    defects: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkforcePerformanceEvent(Base):
    __tablename__ = "workforce_performance_events"
    __table_args__ = (Index("ix_workforce_performance_worker_created", "worker_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workforce_members.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("workforce_assignments.id", ondelete="SET NULL"), index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    reliability_score: Mapped[float] = mapped_column(Float, nullable=False)
    collaboration_score: Mapped[float] = mapped_column(Float, nullable=False)
    policy_score: Mapped[float] = mapped_column(Float, nullable=False)
    learning_score: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class WorkforceHealthReport(Base):
    __tablename__ = "workforce_health_reports"
    __table_args__ = (Index("ix_workforce_health_worker_created", "worker_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workforce_members.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    operational_health: Mapped[float] = mapped_column(Float, nullable=False)
    performance: Mapped[float] = mapped_column(Float, nullable=False)
    collaboration: Mapped[float] = mapped_column(Float, nullable=False)
    trust: Mapped[float] = mapped_column(Float, nullable=False)
    learning: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation: Mapped[str] = mapped_column(String(120), nullable=False)
    restrictions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    incidents: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    generated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class WorkforceIncident(Base, TimestampMixin):
    __tablename__ = "workforce_incidents"
    __table_args__ = (Index("ix_workforce_incidents_worker_status", "worker_id", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workforce_members.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("workforce_assignments.id", ondelete="SET NULL"), index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False, index=True)
    restrictions_applied: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    opened_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    resolved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AcademyCourse(Base, TimestampMixin):
    __tablename__ = "academy_courses"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_academy_course_org_code"),
        Index("ix_academy_courses_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    competencies: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    passing_score: Mapped[float] = mapped_column(Float, default=80.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class AcademyEnrollment(Base, TimestampMixin):
    __tablename__ = "academy_enrollments"
    __table_args__ = (
        UniqueConstraint("course_id", "worker_id", "status", name="uq_academy_active_enrollment"),
        Index("ix_academy_enrollments_worker_status", "worker_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("academy_courses.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workforce_members.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="assigned", nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AcademyAssessment(Base):
    __tablename__ = "academy_assessments"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "attempt_number", name="uq_academy_assessment_attempt"),
        Index("ix_academy_assessments_worker_created", "worker_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    enrollment_id: Mapped[str] = mapped_column(ForeignKey("academy_enrollments.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("academy_courses.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workforce_members.id", ondelete="CASCADE"), nullable=False, index=True)
    assessed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class AcademyCertification(Base, TimestampMixin):
    __tablename__ = "academy_certifications"
    __table_args__ = (
        UniqueConstraint("code", name="uq_academy_certification_code"),
        Index("ix_academy_certifications_worker_status", "worker_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workforce_members.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("academy_courses.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("academy_assessments.id", ondelete="RESTRICT"), nullable=False, index=True)
    issued_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    code: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certification_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class KnowledgeItem(Base, TimestampMixin):
    __tablename__ = "knowledge_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "checksum", name="uq_knowledge_org_checksum"),
        Index("ix_knowledge_items_scope_status", "organization_id", "scope_type", "scope_id", "status"),
        Index("ix_knowledge_items_namespace_subject", "organization_id", "namespace", "subject"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workforce_members.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    verified_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_items.id", ondelete="SET NULL"), index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(160), nullable=False)
    namespace: Mapped[str] = mapped_column(String(120), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeProvenance(Base):
    __tablename__ = "knowledge_provenance"
    __table_args__ = (Index("ix_knowledge_provenance_item", "knowledge_item_id", "collected_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    knowledge_item_id: Mapped[str] = mapped_column(ForeignKey("knowledge_items.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), default="internal", nullable=False)
    author: Mapped[str | None] = mapped_column(String(200))
    uri: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(String(64))
    source_quality: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    direct_evidence: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class ScopedMemory(Base, TimestampMixin):
    __tablename__ = "scoped_memories"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope_type", "scope_id", "key", name="uq_scoped_memory_key"),
        Index("ix_scoped_memories_scope_status", "organization_id", "scope_type", "scope_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    source_item_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_items.id", ondelete="SET NULL"), index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(160), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningEvent(Base, TimestampMixin):
    __tablename__ = "learning_events"
    __table_args__ = (
        Index("ix_learning_events_org_outcome_created", "organization_id", "outcome", "created_at"),
        Index("ix_learning_events_context", "organization_id", "context_fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workforce_members.id", ondelete="SET NULL"), index=True)
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("workforce_assignments.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    verified_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    strategy: Mapped[str | None] = mapped_column(String(200))
    error_fingerprint: Mapped[str | None] = mapped_column(String(64))
    lesson: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="recorded", nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Lesson(Base, TimestampMixin):
    __tablename__ = "lessons"
    __table_args__ = (Index("ix_lessons_org_status_created", "organization_id", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workforce_members.id", ondelete="SET NULL"), index=True)
    source_event_id: Mapped[str | None] = mapped_column(ForeignKey("learning_events.id", ondelete="SET NULL"), index=True)
    promoted_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    lesson: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Autonomous Security & Learning Fabric — durable security admission, evidence,
# rule learning, remediation and release-gate state. Security knowledge itself is
# promoted through the existing verified Knowledge/Learning pipeline above.

class SecurityAccessGrant(Base, TimestampMixin):
    __tablename__ = "security_access_grants"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_security_grant_org_user"),
        Index("ix_security_grants_status_expiry", "status", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    granted_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    level: Mapped[str] = mapped_column(String(32), default="standard", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    profiles: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityTarget(Base, TimestampMixin):
    __tablename__ = "security_targets"
    __table_args__ = (
        UniqueConstraint("organization_id", "origin", name="uq_security_target_org_origin"),
        Index("ix_security_targets_org_auth", "organization_id", "authorization_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    verified_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(500), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    authorization_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    verification_method: Mapped[str] = mapped_column(String(40), nullable=False)
    challenge_hash: Mapped[str | None] = mapped_column(String(64))
    active_scan_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    target_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityScan(Base, TimestampMixin):
    __tablename__ = "security_scans"
    __table_args__ = (
        Index("ix_security_scans_org_status_created", "organization_id", "status", "created_at"),
        Index("ix_security_scans_target_created", "target_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("security_targets.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    profile: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(32), default="passive", nullable=False)
    tool_plan: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    lease_token: Mapped[str | None] = mapped_column(String(36), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityFinding(Base, TimestampMixin):
    __tablename__ = "security_findings"
    __table_args__ = (
        UniqueConstraint("scan_id", "fingerprint", name="uq_security_finding_scan_fingerprint"),
        Index("ix_security_findings_org_state_severity", "organization_id", "state", "severity"),
        Index("ix_security_findings_target_created", "target_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("security_scans.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("security_targets.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="observed", nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    cwe: Mapped[str | None] = mapped_column(String(40))
    owasp: Mapped[str | None] = mapped_column(String(80))
    location: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    remediation: Mapped[str | None] = mapped_column(Text)
    verified_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityRule(Base, TimestampMixin):
    __tablename__ = "security_rules"
    __table_args__ = (
        UniqueConstraint("organization_id", "signature", name="uq_security_rule_org_signature"),
        Index("ix_security_rules_status_trust", "status", "trust_score"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    source_finding_id: Mapped[str | None] = mapped_column(ForeignKey("security_findings.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    rule_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    detector: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="quarantine", nullable=False, index=True)
    trust_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    validation_passes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    validation_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityRuleValidation(Base):
    __tablename__ = "security_rule_validations"
    __table_args__ = (Index("ix_security_rule_validations_rule_created", "rule_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    rule_id: Mapped[str] = mapped_column(ForeignKey("security_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    corpus_id: Mapped[str] = mapped_column(String(120), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class SecurityRemediation(Base, TimestampMixin):
    __tablename__ = "security_remediations"
    __table_args__ = (Index("ix_security_remediations_org_status_created", "organization_id", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("security_findings.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False, index=True)
    worktree_ref: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    regression_result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    retest_scan_id: Mapped[str | None] = mapped_column(ForeignKey("security_scans.id", ondelete="SET NULL"), index=True)
    verified_fixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityReleaseGate(Base):
    __tablename__ = "security_release_gates"
    __table_args__ = (Index("ix_security_release_gate_project_created", "project_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("security_scans.id", ondelete="CASCADE"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    blockers: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


# Phase 29H — provider-neutral Production Studio and mobile delivery persistence.

class StudioJob(Base, TimestampMixin):
    __tablename__ = "studio_jobs"
    __table_args__ = (
        Index("ix_studio_jobs_org_status_created", "organization_id", "status", "created_at"),
        Index("ix_studio_jobs_project_created", "project_id", "created_at"),
        Index("ix_studio_jobs_revision_asset", "revision_of_asset_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    revision_of_asset_id: Mapped[str | None] = mapped_column(String(36), index=True)
    department: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    output_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(35), default="en-US", nullable=False)
    style: Mapped[str] = mapped_column(String(120), default="modern", nullable=False)
    target: Mapped[str | None] = mapped_column(String(240))
    programming_language: Mapped[str | None] = mapped_column(String(40))
    change_note: Mapped[str | None] = mapped_column(Text)
    provider_mode: Mapped[str] = mapped_column(String(40), default="provider_neutral", nullable=False)
    provider: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    safety_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    safety_findings: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    request_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudioAsset(Base, TimestampMixin):
    __tablename__ = "studio_assets"
    __table_args__ = (
        Index("ix_studio_assets_org_status_created", "organization_id", "status", "created_at"),
        Index("ix_studio_assets_project_created", "project_id", "created_at"),
        UniqueConstraint("job_id", name="uq_studio_asset_job"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("studio_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    department: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    asset_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudioAssetRevision(Base, TimestampMixin):
    __tablename__ = "studio_asset_revisions"
    __table_args__ = (
        UniqueConstraint("asset_id", "revision_number", name="uq_studio_asset_revision_number"),
        Index("ix_studio_asset_revisions_asset_created", "asset_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("studio_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("studio_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text)
    revision_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class StudioSafetyReview(Base, TimestampMixin):
    __tablename__ = "studio_safety_reviews"
    __table_args__ = (
        Index("ix_studio_safety_reviews_job_created", "job_id", "created_at"),
        Index("ix_studio_safety_reviews_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("studio_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("studio_assets.id", ondelete="SET NULL"), index=True)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    policy_version: Mapped[str] = mapped_column(String(40), default="29H.1", nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    findings: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class ProjectStudioAttachment(Base, TimestampMixin):
    __tablename__ = "project_studio_attachments"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", name="uq_project_studio_attachment"),
        Index("ix_project_studio_attachments_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("studio_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    attached_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


# Phase 36D — Universal Creative Asset Graph and Media Orchestrator.

class MediaAssetGraph(Base, TimestampMixin):
    __tablename__ = "media_asset_graphs"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_media_graph_org_idempotency"),
        Index("ix_media_graphs_org_status_created", "organization_id", "status", "created_at"),
        Index("ix_media_graphs_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    studio_job_id: Mapped[str | None] = mapped_column(ForeignKey("studio_jobs.id", ondelete="SET NULL"), index=True)
    studio_asset_id: Mapped[str | None] = mapped_column(ForeignKey("studio_assets.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    asset_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    output_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False, index=True)
    graph_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    graph_checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    graph_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rights_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    provenance: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)


class MediaAssetNode(Base, TimestampMixin):
    __tablename__ = "media_asset_nodes"
    __table_args__ = (
        UniqueConstraint("graph_id", "logical_key", "revision", name="uq_media_node_graph_key_revision"),
        UniqueConstraint("graph_id", "idempotency_key", name="uq_media_node_graph_idempotency"),
        Index("ix_media_nodes_graph_status", "graph_id", "status"),
        Index("ix_media_nodes_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    graph_id: Mapped[str] = mapped_column(ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    logical_key: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    node_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    media_type: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False, index=True)
    storage_backend: Mapped[str | None] = mapped_column(String(32))
    storage_key: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    prompt_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rights_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    provenance: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    scene_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    timeline_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    operation_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MediaAssetEdge(Base, TimestampMixin):
    __tablename__ = "media_asset_edges"
    __table_args__ = (
        UniqueConstraint("graph_id", "parent_node_id", "child_node_id", "dependency_type", name="uq_media_edge_dependency"),
        Index("ix_media_edges_graph_ordinal", "graph_id", "ordinal"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    graph_id: Mapped[str] = mapped_column(ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_node_id: Mapped[str] = mapped_column(ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    child_node_id: Mapped[str] = mapped_column(ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    dependency_type: Mapped[str] = mapped_column(String(40), default="input", nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MediaRenderStep(Base, TimestampMixin):
    __tablename__ = "media_render_steps"
    __table_args__ = (
        UniqueConstraint("graph_id", "step_key", name="uq_media_render_step_graph_key"),
        UniqueConstraint("graph_id", "idempotency_key", name="uq_media_render_step_graph_idempotency"),
        Index("ix_media_render_steps_org_status_created", "organization_id", "status", "created_at"),
        Index("ix_media_render_steps_graph_status", "graph_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    graph_id: Mapped[str] = mapped_column(ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id: Mapped[str] = mapped_column(ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    step_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    output_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    engine: Mapped[str] = mapped_column(String(60), default="ffmpeg", nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    hardware_adapter: Mapped[str] = mapped_column(String(40), default="software", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_owner: Mapped[str | None] = mapped_column(String(160), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    input_checksums: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    output_checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    command_hash: Mapped[str | None] = mapped_column(String(64))
    result_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DesignImageExecution(Base, TimestampMixin):
    __tablename__ = "design_image_executions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_design_image_execution_org_idempotency"
        ),
        Index(
            "ix_design_image_executions_org_status_created",
            "organization_id", "status", "created_at",
        ),
        Index(
            "ix_design_image_executions_claim",
            "status", "available_at", "created_at",
        ),
        Index("ix_design_image_executions_graph_status", "graph_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    studio_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("studio_jobs.id", ondelete="SET NULL"), index=True
    )
    studio_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("studio_assets.id", ondelete="SET NULL"), index=True
    )
    graph_id: Mapped[str] = mapped_column(
        ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    operation: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_options: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_format: Mapped[str] = mapped_column(String(16), default="png", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_owner: Mapped[str | None] = mapped_column(String(160), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), index=True)
    provider_response_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    usage_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_basis: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    output_storage_backend: Mapped[str | None] = mapped_column(String(32))
    output_storage_key: Mapped[str | None] = mapped_column(Text)
    output_checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    output_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AudioSpeechExecution(Base, TimestampMixin):
    __tablename__ = "audio_speech_executions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_audio_speech_execution_org_idempotency",
        ),
        Index(
            "ix_audio_speech_executions_org_status_created",
            "organization_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_audio_speech_executions_claim",
            "status",
            "available_at",
            "created_at",
        ),
        Index(
            "ix_audio_speech_executions_graph_status",
            "graph_id",
            "status",
        ),
        Index(
            "ix_audio_speech_executions_provider_state_lookup",
            "provider",
            "provider_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    studio_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("studio_jobs.id", ondelete="SET NULL"), index=True
    )
    studio_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("studio_assets.id", ondelete="SET NULL"), index=True
    )
    graph_id: Mapped[str] = mapped_column(
        ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    operation: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    voice: Mapped[str] = mapped_column(String(80), nullable=False)
    speed: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="planned", nullable=False, index=True
    )
    provider_state: Mapped[str] = mapped_column(
        String(40), default="not_started", nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    instructions_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    input_characters: Mapped[int] = mapped_column(Integer, nullable=False)
    request_options: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_format: Mapped[str] = mapped_column(String(16), default="wav", nullable=False)
    max_duration_seconds: Mapped[float] = mapped_column(Float, default=60.0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_owner: Mapped[str | None] = mapped_column(String(160), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    fencing_token: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), index=True)
    provider_response_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    usage_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_cost_usd: Mapped[float] = mapped_column(Float, default=0.05, nullable=False)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_basis: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    output_storage_backend: Mapped[str | None] = mapped_column(String(32))
    output_storage_key: Mapped[str | None] = mapped_column(Text)
    output_checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    output_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    output_duration_seconds: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VideoExecution(Base, TimestampMixin):
    __tablename__ = "video_executions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_video_execution_org_idempotency"
        ),
        UniqueConstraint("provider", "provider_job_id", name="uq_video_execution_provider_job"),
        Index(
            "ix_video_executions_org_status_created",
            "organization_id", "status", "created_at",
        ),
        Index(
            "ix_video_executions_claim",
            "status", "available_at", "created_at",
        ),
        Index("ix_video_executions_graph_status", "graph_id", "status"),
        Index("ix_video_executions_provider_state_lookup", "provider", "provider_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    studio_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("studio_jobs.id", ondelete="SET NULL"), index=True
    )
    studio_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("studio_assets.id", ondelete="SET NULL"), index=True
    )
    graph_id: Mapped[str] = mapped_column(
        ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scene_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_options: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_format: Mapped[str] = mapped_column(String(16), default="mp4", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    poll_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_polls: Mapped[int] = mapped_column(Integer, default=360, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_owner: Mapped[str | None] = mapped_column(String(160), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(240), index=True)
    provider_state: Mapped[str] = mapped_column(String(40), default="not_started", nullable=False, index=True)
    provider_progress: Mapped[int | None] = mapped_column(Integer)
    provider_response_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    usage_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_basis: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    output_storage_backend: Mapped[str | None] = mapped_column(String(32))
    output_storage_key: Mapped[str | None] = mapped_column(Text)
    output_checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    output_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ThreeDGenerationJob(Base, TimestampMixin):
    __tablename__ = "three_d_generation_jobs"
    __table_args__ = (
        Index("ix_three_d_jobs_org_status_created", "organization_id", "status", "created_at"),
        Index("ix_three_d_jobs_project_created", "project_id", "created_at"),
        Index("ix_three_d_jobs_user_created", "requested_by_id", "created_at"),
        Index("ix_three_d_jobs_trace", "trace_id"),
        UniqueConstraint("provider", "provider_job_id", name="uq_three_d_jobs_provider_job"),
        UniqueConstraint("idempotency_key", name="uq_three_d_jobs_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="runpod", nullable=False)
    provider_job_id: Mapped[str | None] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(64), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    input_content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    input_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), default=uuid_str, nullable=False)
    request_options: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    provider_delay_ms: Mapped[int | None] = mapped_column(BigInteger)
    provider_execution_ms: Mapped[int | None] = mapped_column(BigInteger)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metering_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ThreeDArtifact(Base, TimestampMixin):
    __tablename__ = "three_d_artifacts"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_three_d_artifacts_job"),
        Index("ix_three_d_artifacts_project_created", "project_id", "created_at"),
        Index("ix_three_d_artifacts_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("three_d_generation_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), default="model/gltf-binary", nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ready", nullable=False, index=True)
    artifact_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class MobileRelease(Base, TimestampMixin):
    __tablename__ = "mobile_releases"
    __table_args__ = (
        UniqueConstraint("platform", "version", "build_number", "channel", name="uq_mobile_release_identity"),
        Index("ix_mobile_releases_platform_status_created", "platform", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    build_number: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(40), default="internal", nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signing_status: Mapped[str] = mapped_column(String(40), nullable=False)
    publication_status: Mapped[str] = mapped_column(String(40), default="not_published", nullable=False)
    source_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_path: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    release_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MobileReleaseArtifact(Base, TimestampMixin):
    __tablename__ = "mobile_release_artifacts"
    __table_args__ = (
        UniqueConstraint("release_id", "artifact_type", name="uq_mobile_release_artifact_type"),
        Index("ix_mobile_release_artifacts_release_status", "release_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    release_id: Mapped[str] = mapped_column(ForeignKey("mobile_releases.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    signed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    signature_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ready", nullable=False)


class MobileValidationRun(Base, TimestampMixin):
    __tablename__ = "mobile_validation_runs"
    __table_args__ = (
        Index("ix_mobile_validation_runs_release_operation", "release_id", "operation", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    release_id: Mapped[str] = mapped_column(ForeignKey("mobile_releases.id", ondelete="CASCADE"), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GrowthIntegrationConnection(Base, TimestampMixin):
    """Provider-neutral GS-10 integration configuration with opaque credentials only."""

    __tablename__ = "growth_integration_connections"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "integration_type",
            "name",
            name="uq_growth_integration_org_type_name",
        ),
        Index(
            "ix_growth_integrations_org_type_status",
            "organization_id",
            "integration_type",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    integration_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    last_simulated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_delivery_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    live_provider_call: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthTeamAssignment(Base, TimestampMixin):
    """Tenant-scoped workflow role assignment for Growth & Social resources."""

    __tablename__ = "growth_team_assignments"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            "scope_type",
            "scope_id",
            name="uq_growth_team_assignment_scope",
        ),
        Index(
            "ix_growth_team_assignments_org_scope_active",
            "organization_id",
            "scope_type",
            "active",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(160), nullable=False)
    role_key: Mapped[str] = mapped_column(String(32), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    approval_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthReportDefinition(Base, TimestampMixin):
    """Durable scheduled report definition; delivery remains disabled in GS-10."""

    __tablename__ = "growth_report_definitions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name", name="uq_growth_report_definition_org_name"
        ),
        Index(
            "ix_growth_report_definitions_org_schedule_active",
            "organization_id",
            "schedule_kind",
            "active",
        ),
        Index("ix_growth_report_definitions_next_run", "next_run_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    report_type: Mapped[str] = mapped_column(String(40), nullable=False)
    formats: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    filters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    schedule_kind: Mapped[str] = mapped_column(
        String(24), default="manual", nullable=False
    )
    timezone_name: Mapped[str] = mapped_column(
        String(80), default="UTC", nullable=False
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    brand_name: Mapped[str | None] = mapped_column(String(180))
    custom_domain: Mapped[str | None] = mapped_column(String(253))
    branding: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    external_delivery_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class GrowthReportRun(Base, TimestampMixin):
    """GS-10 report snapshot and deterministic artifact manifest."""

    __tablename__ = "growth_report_runs"
    __table_args__ = (
        Index(
            "ix_growth_report_runs_org_status_created",
            "organization_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_growth_report_runs_definition_created",
            "report_definition_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_definition_id: Mapped[str] = mapped_column(
        ForeignKey("growth_report_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    triggered_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    artifact_manifest: Mapped[list[dict]] = mapped_column(
        JSON, default=list, nullable=False
    )
    simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    external_delivery_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)



class GrowthControlledPilot(Base, TimestampMixin):
    """Fail-closed GS-12 controlled live-pilot gate and authorization record."""

    __tablename__ = "growth_controlled_pilots"
    __table_args__ = (
        Index(
            "ix_growth_controlled_pilots_org_provider_status",
            "organization_id",
            "provider",
            "status",
        ),
        Index("ix_growth_controlled_pilots_expires_at", "expires_at"),
        Index(
            "uq_growth_controlled_pilots_live_scope",
            "provider",
            "scope_ref",
            unique=True,
            postgresql_where=text("real_spend_allowed IS TRUE"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider_scope: Mapped[str] = mapped_column(String(80), nullable=False)
    scope_ref: Mapped[str | None] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)

    owner_approved_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    owner_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_approval_reference: Mapped[str | None] = mapped_column(String(240))

    legal_policy_acknowledged: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    legal_policy_reference: Mapped[str | None] = mapped_column(String(500))
    legal_acknowledged_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    legal_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    currency: Mapped[str | None] = mapped_column(String(3))
    max_total_budget_minor: Mapped[int | None] = mapped_column(BigInteger)
    max_daily_budget_minor: Mapped[int | None] = mapped_column(BigInteger)
    max_cpa_minor: Mapped[int | None] = mapped_column(BigInteger)
    min_roas: Mapped[float | None] = mapped_column(Float)

    launch_authorized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    launch_authorized_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    launch_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disarmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    live_provider_mutation_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    real_spend_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    blocked_reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
