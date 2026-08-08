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
    """Durable single-server project planning execution requested by a user."""

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
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), default="not_requested", nullable=False)
    rework_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
