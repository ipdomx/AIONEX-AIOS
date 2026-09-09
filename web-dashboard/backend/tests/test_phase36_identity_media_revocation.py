from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import identity_media as endpoint_module
from app.services import identity_media_access, identity_media_worker as worker_module
from app.services.identity_media_runtime import IdentityMediaClaim


class Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def commit(self):
        pass

    async def rollback(self):
        pass


def execution(**overrides):
    values = {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "organization_id": "org-identity-revoke",
        "requested_by_id": "user-identity-revoke",
        "operation": "voice_clone",
        "identity_basis": "self",
        "subject_reference": "self-test-subject",
        "provider_job_id": None,
        "secondary_provider_job_id": None,
        "request_payload": {"script": "A fictional test line."},
        "status": "queued",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def deny(monkeypatch):
    checker = AsyncMock(
        return_value=identity_media_access.IdentityMediaAccessDecision(
            "voice_clone", "self", False, True, "owner-override", "owner-deny", True
        )
    )
    # raising=False deliberately permits the pre-fix source to run, so these
    # tests reproduce a missing check rather than fail merely on a new import.
    monkeypatch.setattr(identity_media_access, "execution_access", checker, raising=False)
    monkeypatch.setattr(worker_module, "execution_access", checker, raising=False)
    return checker


def worker_harness(monkeypatch, row):
    session = Session()
    monkeypatch.setattr(worker_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(worker_module, "load_claim", AsyncMock(return_value=row))
    for name in ("record_primary_submission", "record_secondary_submission", "release_for_poll"):
        monkeypatch.setattr(worker_module, name, AsyncMock())
    failure = AsyncMock()
    monkeypatch.setattr(worker_module, "fail_execution", failure)
    adapter = SimpleNamespace(
        create_prediction=AsyncMock(
            return_value=SimpleNamespace(prediction_id="private-test-id", status="starting")
        ),
        get_prediction=AsyncMock(
            return_value=SimpleNamespace(status="starting", metrics={})
        ),
        download_output=AsyncMock(),
    )
    worker = object.__new__(worker_module.IdentityMediaWorker)
    worker.adapter = adapter
    worker.poll_seconds = 3
    worker._input_file = AsyncMock(return_value=SimpleNamespace(url="https://example.invalid/private-input"))
    claim = IdentityMediaClaim(row.id, "test-claim", 1, "submit")
    return worker, adapter, session, claim, failure


@pytest.mark.asyncio
async def test_revoked_queued_execution_does_not_submit_to_provider(monkeypatch):
    row = execution()
    worker, adapter, _session, claim, failure = worker_harness(monkeypatch, row)
    deny(monkeypatch)

    await worker._submit(claim)

    adapter.create_prediction.assert_not_awaited()
    worker._input_file.assert_not_awaited()
    failure.assert_awaited_once()
    assert failure.await_args.kwargs["code"] == "identity_media_access_revoked"
    assert failure.await_args.kwargs["needs_review"] is False


@pytest.mark.asyncio
async def test_revoked_running_execution_preserves_job_for_review(monkeypatch):
    row = execution(provider_job_id="private-existing-job", status="provider_running")
    worker, adapter, _session, claim, failure = worker_harness(monkeypatch, row)
    deny(monkeypatch)

    await worker._poll(claim)

    adapter.get_prediction.assert_not_awaited()
    adapter.create_prediction.assert_not_awaited()
    adapter.download_output.assert_not_awaited()
    failure.assert_awaited_once()
    assert failure.await_args.kwargs["needs_review"] is True
    assert row.provider_job_id == "private-existing-job"


@pytest.mark.asyncio
async def test_revocation_between_clone_and_speech_prevents_second_submission(monkeypatch):
    row = execution(provider_job_id="private-clone-job", status="provider_running")
    worker, adapter, session, claim, failure = worker_harness(monkeypatch, row)
    adapter.get_prediction.return_value = SimpleNamespace(
        status="succeeded", metrics={}, output={"voice_id": "private-test-voice"}
    )
    deny(monkeypatch)

    await worker._poll_voice_clone(session, row, claim)

    adapter.create_prediction.assert_not_awaited()
    failure.assert_awaited_once()
    assert failure.await_args.kwargs["needs_review"] is True


@pytest.mark.asyncio
async def test_revoked_completed_output_cannot_be_downloaded(monkeypatch):
    row = execution(status="completed", output_storage_key="private/output.mp3", output_media_type="audio/mpeg")
    session = SimpleNamespace(scalar=AsyncMock(return_value=row))
    store = SimpleNamespace(presigned_get=lambda *_args, **_kwargs: "https://example.invalid/output")
    monkeypatch.setattr(endpoint_module, "media_object_store", lambda: store)
    deny(monkeypatch)

    with pytest.raises(HTTPException) as captured:
        await endpoint_module.download_execution(
            row.id,
            actor=SimpleNamespace(id=row.requested_by_id, organization_id=row.organization_id),
            session=session,
        )
    assert captured.value.status_code == 403


@pytest.mark.asyncio
async def test_revoked_signed_provider_input_is_not_delivered(monkeypatch):
    from app.services.identity_media_replicate import issue_provider_input_token

    secret = "identity-revocation-fixture-" + ("r" * 40)
    row = execution(
        status="provider_running",
        input_storage_keys={"audio": "private/source.wav"},
        request_payload={
            "input_content_types": {"audio": "audio/wav"},
            "input_filenames": {"audio": "source.wav"},
        },
    )
    grant = issue_provider_input_token(
        execution_id=row.id, input_name="audio", secret=secret, ttl_seconds=60
    )
    session = SimpleNamespace(scalar=AsyncMock(return_value=row))
    store = SimpleNamespace(get_bytes=lambda *_args, **_kwargs: b"RIFF-private-test-audio")
    monkeypatch.setattr(endpoint_module, "settings", SimpleNamespace(
        SECRET_KEY=secret, IDENTITY_MEDIA_MAX_PROVIDER_BYTES=1024
    ))
    monkeypatch.setattr(endpoint_module, "media_object_store", lambda: store)
    deny(monkeypatch)

    with pytest.raises(HTTPException) as captured:
        await endpoint_module.provider_input(grant, "source.wav", session=session)
    assert captured.value.status_code == 404


def authorities(**overrides):
    user = SimpleNamespace(
        id="user-identity-revoke", organization_id="org-identity-revoke",
        deleted_at=None, status="active", role_id=None,
    )
    organization = SimpleNamespace(status="active")
    account = SimpleNamespace(status="active")
    return {"user": user, "organization": organization, "account": account, **overrides}


@pytest.mark.asyncio
@pytest.mark.parametrize("case,reason", [
    ("user-missing", "user-unavailable"),
    ("user-deleted", "user-unavailable"),
    ("user-suspended", "user-unavailable"),
    ("organization-missing", "organization-inactive"),
    ("organization-suspended", "organization-inactive"),
    ("role-missing", "role-unavailable"),
    ("role-suspended", "role-unavailable"),
    ("role-other-tenant", "role-unavailable"),
    ("account-missing", "account-suspended"),
    ("account-suspended", "account-suspended"),
    ("project-missing", "project-unavailable"),
])
async def test_durable_authorization_rejects_unavailable_current_authority(monkeypatch, case, reason):
    values = authorities()
    row = execution(project_id=None)
    role = SimpleNamespace(status="active", organization_id=row.organization_id)
    if case == "user-missing":
        values["user"] = None
    elif case == "user-deleted":
        values["user"].deleted_at = "deleted"
    elif case == "user-suspended":
        values["user"].status = "suspended"
    elif case == "organization-missing":
        values["organization"] = None
    elif case == "organization-suspended":
        values["organization"].status = "suspended"
    elif case.startswith("role-"):
        values["user"].role_id = "role-test"
        if case == "role-missing":
            role = None
        elif case == "role-suspended":
            role.status = "suspended"
        else:
            role.organization_id = "another-tenant"
    elif case == "account-missing":
        values["account"] = None
    elif case == "account-suspended":
        values["account"].status = "suspended"
    elif case == "project-missing":
        row.project_id = "deleted-project"
    answers = [values["user"], values["organization"]]
    if case.startswith("role-"):
        answers.append(role)
    answers.append(values["account"])
    if row.project_id:
        answers.append(None)
    session = SimpleNamespace(scalar=AsyncMock(side_effect=answers))
    policy = AsyncMock()
    monkeypatch.setattr(identity_media_access, "effective_access", policy)

    result = await identity_media_access.execution_access(session, row)

    assert result.allowed is False
    assert result.reason == reason
    policy.assert_not_awaited()
    for call in session.scalar.await_args_list:
        assert call.args[0].get_execution_options()["populate_existing"] is True
    user_query = session.scalar.await_args_list[0].args[0]
    assert row.organization_id in user_query.compile().params.values()
    assert row.requested_by_id in user_query.compile().params.values()


@pytest.mark.asyncio
async def test_durable_authorization_preserves_allowed_fictional_and_owner_scope(monkeypatch):
    values = authorities()
    values["organization"].status = "trial"
    values["user"].role_id = "role-test"
    row = execution(project_id="project-test", identity_basis="fictional_inspired")
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[
        values["user"], values["organization"],
        SimpleNamespace(status="active", organization_id=row.organization_id),
        values["account"], SimpleNamespace(id=row.project_id),
    ]))
    monkeypatch.setattr(identity_media_access.billing, "billing_context", AsyncMock(
        return_value={"account": values["account"]}
    ))
    owner_record = AsyncMock(return_value=None)
    monkeypatch.setattr(identity_media_access, "_access_record", owner_record)

    result = await identity_media_access.execution_access(session, row)

    assert result.allowed is True
    assert result.reason == "fictional-direct"
    owner_record.assert_awaited_once()
    assert owner_record.await_args.kwargs["user_id"] == row.requested_by_id


@pytest.mark.asyncio
async def test_owner_override_query_refreshes_cached_authority():
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    await identity_media_access._access_record(session, user_id="user-test", operation="voice_clone")
    statement = session.scalar.await_args.args[0]
    assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.asyncio
async def test_revocation_during_input_preflight_prevents_primary_submission(monkeypatch):
    row = execution()
    worker, adapter, _session, claim, failure = worker_harness(monkeypatch, row)
    checker = deny(monkeypatch)
    checker.side_effect = [SimpleNamespace(allowed=True), SimpleNamespace(allowed=False)]

    await worker._submit(claim)

    worker._input_file.assert_awaited_once()
    adapter.create_prediction.assert_not_awaited()
    failure.assert_awaited_once()


@pytest.mark.asyncio
async def test_allowed_output_is_proxied_without_bearer_redirect(monkeypatch):
    row = execution(status="completed", output_storage_key="private/output.mp3", output_media_type="audio/mpeg")
    session = SimpleNamespace(scalar=AsyncMock(return_value=row))
    def reject_presign(*_args, **_kwargs):
        raise AssertionError("Identity output must not bypass future revocation")
    store = SimpleNamespace(
        presigned_get=reject_presign,
        get_bytes=lambda *_args, **_kwargs: b"ID3-private-test-output",
    )
    monkeypatch.setattr(endpoint_module, "media_object_store", lambda: store)
    monkeypatch.setattr(endpoint_module, "settings", SimpleNamespace(IDENTITY_MEDIA_MAX_PROVIDER_BYTES=1024))
    checker = deny(monkeypatch)
    checker.return_value = SimpleNamespace(allowed=True)

    response = await endpoint_module.download_execution(
        row.id,
        actor=SimpleNamespace(id=row.requested_by_id, organization_id=row.organization_id),
        session=session,
    )

    assert response.body == b"ID3-private-test-output"
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert checker.await_count == 2


@pytest.mark.asyncio
async def test_revocation_during_output_read_prevents_delivery(monkeypatch):
    row = execution(status="completed", output_storage_key="private/output.mp3", output_media_type="audio/mpeg")
    session = SimpleNamespace(scalar=AsyncMock(return_value=row))
    monkeypatch.setattr(endpoint_module, "media_object_store", lambda: SimpleNamespace(
        get_bytes=lambda *_args, **_kwargs: b"ID3-private-test-output"
    ))
    monkeypatch.setattr(endpoint_module, "settings", SimpleNamespace(IDENTITY_MEDIA_MAX_PROVIDER_BYTES=1024))
    checker = deny(monkeypatch)
    checker.side_effect = [SimpleNamespace(allowed=True), SimpleNamespace(allowed=False)]

    with pytest.raises(HTTPException) as captured:
        await endpoint_module.download_execution(
            row.id,
            actor=SimpleNamespace(id=row.requested_by_id, organization_id=row.organization_id),
            session=session,
        )
    assert captured.value.status_code == 403
