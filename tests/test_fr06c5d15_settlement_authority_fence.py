"""Execute the embedded settlement program with explicit DB boundary doubles.

No real SQL connection or provider call occurs. These tests prove the embedded
program's control flow; real PostgreSQL lock behavior remains a separate gate.
"""
from __future__ import annotations

import hashlib
import sys
from types import ModuleType, SimpleNamespace

import pytest
from scripts.security import fr06c5d15_identity_media_terminal_reconcile as m

OP = "11111111-1111-4111-8111-111111111111"
GEN = 41


def harness(monkeypatch, change):
    current = dict(schema_version=8, generation=GEN, status="closed", enabled=False,
                   operation_id=OP, full_host_closure=False)
    current.update(change)
    state = SimpleNamespace(**current)
    row = SimpleNamespace(id="exec-0", provider="replicate", status="failed",
                          provider_state="starting", version=3,
                          provider_job_id="synthetic-job", lease_token=None,
                          secondary_provider_job_id=None, completed_at=object(),
                          organization_id="synthetic-org", requested_by_id="synthetic-owner")
    trace = []

    class Column:
        def __eq__(self, other):
            return ("synthetic-condition", other)

    class Query:
        def where(self, *args):
            return self
        def with_for_update(self):
            trace.append("execution-lock-request")
            return self

    class Transaction:
        async def __aenter__(self):
            session.in_transaction = True
        async def __aexit__(self, typ, value, tb):
            trace.append("rollback" if typ else "commit")
            session.in_transaction = False

    class Session:
        in_transaction = False
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        def begin(self):
            return Transaction()
        async def scalar(self, statement):
            trace.append("execution-read")
            return row
        def add(self, value):
            trace.append(("audit", value.details))

    session = Session()
    async def read_admission(s, *, required_scope):
        assert s is session and s.in_transaction
        assert required_scope == "realtime_media_requests"
        trace.append("authority-share-lock-in-same-transaction")
        return state

    def module(name, **attrs):
        result = ModuleType(name)
        result.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, result)

    for name in ("app", "app.db", "app.services"):
        module(name)
    module("sqlalchemy", select=lambda *args: Query())
    module("app.db.base", SessionLocal=lambda: session)
    module("app.db.models", IdentityMediaExecution=SimpleNamespace(id=Column()),
           AuditEvent=lambda **attrs: SimpleNamespace(**attrs))
    module("app.services.host_maintenance_admission", read_admission_snapshot=read_admission)
    job_hash = hashlib.sha256(b"synthetic-job").hexdigest()
    monkeypatch.setattr(sys, "argv", ["-c", row.id, "3", job_hash, "failed", OP, str(GEN)])
    return row, trace


@pytest.mark.parametrize("change", [
    {"status": "open", "enabled": True},
    {"generation": GEN + 1},
    {"operation_id": "22222222-2222-4222-8222-222222222222"},
    {"full_host_closure": True},
])
def test_embedded_settlement_refuses_authority_drift_before_row_write(monkeypatch, change):
    row, trace = harness(monkeypatch, change)
    with pytest.raises(RuntimeError, match="maintenance authority"):
        exec(compile(m.SETTLE, "<embedded-settlement>", "exec"), {})
    assert row.provider_state == "starting" and row.version == 3
    assert "execution-read" not in trace
    assert "rollback" in trace


def test_embedded_settlement_holds_shared_authority_through_commit(monkeypatch):
    row, trace = harness(monkeypatch, {})
    exec(compile(m.SETTLE, "<embedded-settlement>", "exec"), {})
    assert trace[0] == "authority-share-lock-in-same-transaction"
    assert trace[-1] == "commit"
    assert row.provider_state == "failed" and row.version == 4
    audit = next(x[1] for x in trace if isinstance(x, tuple))
    assert audit["maintenance_operation_id"] == OP
    assert audit["maintenance_generation"] == GEN
