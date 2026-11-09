"""FR-23C: an unconfigured store must answer 503, never 500 with the raw error text."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import mobile_store_billing as endpoint
from app.services import mobile_store_billing as service


def test_unconfigured_apple_verifier_is_a_typed_error(monkeypatch, tmp_path):
    monkeypatch.setattr(service.settings, "APP_STORE_ROOT_CERTIFICATES_DIR", str(tmp_path))
    with pytest.raises(service.StoreVerificationUnavailable):
        service._apple_verifier()


def test_reconcile_maps_unconfigured_store_to_503(monkeypatch):
    async def unavailable(*args, **kwargs):
        raise service.StoreVerificationUnavailable("Apple root certificates are not configured")

    monkeypatch.setattr(service, "reconcile_user_store", unavailable)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(endpoint.reconcile("app_store", actor=object(), session=object()))
    assert caught.value.status_code == 503
    assert "certificates" not in str(caught.value.detail)
