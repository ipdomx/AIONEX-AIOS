from __future__ import annotations

from pathlib import Path

from sqlalchemy import (
    CheckConstraint,
    Constraint,
    ForeignKeyConstraint,
    Table,
    UniqueConstraint,
)

from app.db import models  # noqa: F401
from app.db.base import Base

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "web-dashboard/backend/alembic/versions/20260824_0040_realtime_admission.py"
)

EXPECTED_TABLES = {
    "realtime_tenant_quotas",
    "realtime_rooms",
    "realtime_participants",
    "realtime_admission_grants",
}


def _constraint_names(table: Table, kind: type[Constraint]) -> set[str]:
    names: set[str] = set()
    for constraint in table.constraints:
        if isinstance(constraint, kind) and constraint.name is not None:
            names.add(str(constraint.name))
    return names


def _foreign_key_signature(
    constraint: ForeignKeyConstraint,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    local = tuple(element.parent.name for element in constraint.elements)
    remote = tuple(element.target_fullname for element in constraint.elements)
    return local, remote


def test_realtime_admission_tables_and_required_columns_are_registered() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)

    expected_columns = {
        "realtime_tenant_quotas": {
            "id",
            "organization_id",
            "enabled",
            "max_concurrent_rooms",
            "max_participants_per_room",
            "max_concurrent_participants",
            "max_publishers_per_room",
            "max_screen_shares_per_room",
            "max_concurrent_recordings",
            "admission_window_seconds",
            "max_admissions_per_window",
            "grant_ttl_seconds",
            "policy",
            "version",
        },
        "realtime_rooms": {
            "id",
            "organization_id",
            "workspace_id",
            "project_id",
            "created_by_id",
            "room_key",
            "idempotency_key",
            "room_type",
            "media_mode",
            "status",
            "provider_adapter",
            "provider_room_id_sha256",
            "max_participants",
            "allow_screen_share",
            "recording_policy",
            "encryption_policy",
            "admission_policy",
            "fencing_token",
            "opened_at",
            "closed_at",
            "expires_at",
            "version",
        },
        "realtime_participants": {
            "id",
            "organization_id",
            "room_id",
            "user_id",
            "participant_key",
            "role",
            "status",
            "can_publish",
            "can_subscribe",
            "can_screen_share",
            "hidden",
            "node_id",
            "connection_count",
            "capabilities",
            "joined_at",
            "last_seen_at",
            "left_at",
            "revoked_at",
            "version",
        },
        "realtime_admission_grants": {
            "id",
            "organization_id",
            "room_id",
            "participant_id",
            "user_id",
            "issued_by_id",
            "idempotency_key",
            "grant_digest_sha256",
            "provider_token_jti_sha256",
            "provider_adapter",
            "role",
            "permissions",
            "status",
            "single_use",
            "issued_at",
            "expires_at",
            "consumed_at",
            "revoked_at",
            "consumed_by_node",
            "version",
        },
    }
    for table_name, columns in expected_columns.items():
        assert columns <= set(Base.metadata.tables[table_name].c.keys()), table_name


def test_room_participant_and_grant_constraints_preserve_tenant_scope() -> None:
    users = Base.metadata.tables["users"]
    workspaces = Base.metadata.tables["workspaces"]
    projects = Base.metadata.tables["projects"]
    rooms = Base.metadata.tables["realtime_rooms"]
    participants = Base.metadata.tables["realtime_participants"]
    grants = Base.metadata.tables["realtime_admission_grants"]

    assert {"uq_users_id_org"} <= _constraint_names(users, UniqueConstraint)
    assert {"uq_workspace_id_org"} <= _constraint_names(workspaces, UniqueConstraint)
    assert {"uq_project_id_org"} <= _constraint_names(projects, UniqueConstraint)

    assert {
        "uq_realtime_room_id_org",
        "uq_realtime_room_org_key",
        "uq_realtime_room_org_idempotency",
    } <= _constraint_names(rooms, UniqueConstraint)
    assert {
        "uq_realtime_participant_id_org",
        "uq_realtime_participant_org_room_key",
    } <= _constraint_names(participants, UniqueConstraint)
    assert {
        "uq_realtime_grant_org_idempotency",
        "uq_realtime_grant_digest",
    } <= _constraint_names(grants, UniqueConstraint)

    room_fks = {
        _foreign_key_signature(constraint)
        for constraint in rooms.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    participant_fks = {
        _foreign_key_signature(constraint)
        for constraint in participants.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    grant_fks = {
        _foreign_key_signature(constraint)
        for constraint in grants.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert (
        ("workspace_id", "organization_id"),
        ("workspaces.id", "workspaces.organization_id"),
    ) in room_fks
    assert (
        ("project_id", "organization_id"),
        ("projects.id", "projects.organization_id"),
    ) in room_fks
    assert (
        ("created_by_id", "organization_id"),
        ("users.id", "users.organization_id"),
    ) in room_fks
    assert (
        ("room_id", "organization_id"),
        ("realtime_rooms.id", "realtime_rooms.organization_id"),
    ) in participant_fks
    assert (
        ("user_id", "organization_id"),
        ("users.id", "users.organization_id"),
    ) in participant_fks
    assert (
        ("room_id", "organization_id"),
        ("realtime_rooms.id", "realtime_rooms.organization_id"),
    ) in grant_fks
    assert (
        ("participant_id", "organization_id"),
        (
            "realtime_participants.id",
            "realtime_participants.organization_id",
        ),
    ) in grant_fks
    assert (
        ("user_id", "organization_id"),
        ("users.id", "users.organization_id"),
    ) in grant_fks
    assert (
        ("issued_by_id", "organization_id"),
        ("users.id", "users.organization_id"),
    ) in grant_fks


def test_quota_and_grant_checks_are_fail_closed() -> None:
    quotas = Base.metadata.tables["realtime_tenant_quotas"]
    rooms = Base.metadata.tables["realtime_rooms"]
    participants = Base.metadata.tables["realtime_participants"]
    grants = Base.metadata.tables["realtime_admission_grants"]

    assert {
        "ck_realtime_quota_room_limit",
        "ck_realtime_quota_room_participant_limit",
        "ck_realtime_quota_tenant_participant_limit",
        "ck_realtime_quota_publisher_limit",
        "ck_realtime_quota_screen_share_limit",
        "ck_realtime_quota_recording_limit",
        "ck_realtime_quota_admission_window",
        "ck_realtime_quota_admission_rate",
        "ck_realtime_quota_grant_ttl",
    } <= _constraint_names(quotas, CheckConstraint)
    assert {
        "ck_realtime_room_participant_limit",
        "ck_realtime_room_fencing_token",
    } <= _constraint_names(rooms, CheckConstraint)
    assert {"ck_realtime_participant_connection_count"} <= _constraint_names(
        participants, CheckConstraint
    )
    assert {"ck_realtime_grant_expiry_after_issue"} <= _constraint_names(
        grants, CheckConstraint
    )


def test_admission_authority_persists_hashes_not_raw_credentials() -> None:
    grant_columns = set(Base.metadata.tables["realtime_admission_grants"].c.keys())
    assert {
        "token",
        "grant_token",
        "provider_token",
        "credential",
        "secret",
        "raw_token",
    }.isdisjoint(grant_columns)
    assert "grant_digest_sha256" in grant_columns
    assert "provider_token_jti_sha256" in grant_columns


def test_migration_0040_is_linear_reversible_and_creates_only_durable_authority() -> (
    None
):
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "20260824_0040"' in source
    assert 'down_revision: str | None = "20260823_0039"' in source
    for table_name in EXPECTED_TABLES:
        assert f'"{table_name}"' in source
    assert "def downgrade() -> None:" in source
    assert source.index('"realtime_admission_grants"') < source.rindex(
        '"realtime_tenant_quotas"'
    )
    assert "SFU" not in source
    assert "TURN" not in source
    assert "provider request" not in source.lower()
