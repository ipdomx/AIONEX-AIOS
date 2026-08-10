from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

import pytest

from app.db.base import SessionLocal
from app.db.models import BillingPlan, BillingPrice

from app.services import mobile_store_billing as billing


def test_google_state_normalization_keeps_cancelled_access_until_expiry():
    future = (
        (datetime.now(timezone.utc) + timedelta(days=10))
        .isoformat()
        .replace("+00:00", "Z")
    )
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_CANCELED",
        "startTime": "2026-08-01T00:00:00Z",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "lineItems": [
            {
                "productId": "pro.monthly",
                "expiryTime": future,
                "autoRenewingPlan": {"autoRenewEnabled": False},
            }
        ],
    }
    result = billing._normalize_google(payload)
    assert result["status"] == "active"
    assert result["auto_renewing"] is False


def test_google_grace_and_hold_states_are_distinct():
    base = {
        "startTime": "2026-08-01T00:00:00Z",
        "lineItems": [
            {"productId": "pro.monthly", "expiryTime": "2026-09-01T00:00:00Z"}
        ],
    }
    grace = billing._normalize_google(
        {**base, "subscriptionState": "SUBSCRIPTION_STATE_IN_GRACE_PERIOD"}
    )
    hold = billing._normalize_google(
        {**base, "subscriptionState": "SUBSCRIPTION_STATE_ON_HOLD"}
    )
    assert grace["status"] == "grace_period"
    assert hold["status"] == "on_hold"


def test_google_tokens_are_encrypted_and_hashable_without_plaintext_storage():
    token = "test-purchase-token-sensitive"
    ciphertext = billing._encrypt_token(token)
    assert token not in ciphertext
    assert billing._decrypt_token(ciphertext) == token
    assert len(billing._token_hash(token)) == 64


def test_store_callback_and_reconciliation_routes_are_registered():
    root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "app").is_dir() and (parent / "alembic").is_dir()
    )
    endpoint = (root / "app/api/v1/endpoints/mobile_store_billing.py").read_text()
    router = (root / "app/api/v1/router.py").read_text()
    assert '@router.post("/notifications/app-store"' in endpoint
    assert '@router.post("/notifications/google-play"' in endpoint
    assert '@router.post("/reconcile/{store}")' in endpoint
    assert 'prefix="/billing/mobile-store"' in router


def test_official_apple_verifier_dependency_imports():
    from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
    from appstoreserverlibrary.api_client import AsyncAppStoreServerAPIClient

    assert SignedDataVerifier and AsyncAppStoreServerAPIClient


def test_migration_persists_replay_events_and_encrypted_google_token():
    root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "app").is_dir() and (parent / "alembic").is_dir()
    )
    migration = (
        root / "alembic/versions/20260809_0012_mobile_store_billing.py"
    ).read_text()
    assert "mobile_store_events" in migration
    assert "purchase_token_ciphertext" in migration
    assert "uq_mobile_store_event_external" in migration


@pytest.mark.asyncio
async def test_owner_can_create_disable_and_diagnose_mobile_store_mapping() -> None:
    suffix = uuid.uuid4().hex[:10]
    plan_code = f"store-plan-{suffix}"
    period_code = f"monthly-{suffix}"
    async with SessionLocal() as session:
        plan = BillingPlan(
            code=plan_code,
            name=f"Store Plan {suffix}",
            status="active",
            default_currency="USD",
            limits={},
            entitlements=["projects"],
            metering={},
            source_version=1,
            source_hash=(suffix * 7)[:64],
        )
        session.add(plan)
        await session.flush()
        price = BillingPrice(
            plan_id=plan.id,
            period_code=period_code,
            months=1,
            amount_minor=999,
            currency="USD",
            enabled=True,
            provider="stripe",
            price_metadata={},
        )
        session.add(price)
        await session.commit()

        created = await billing.owner_upsert_store_mapping(
            session,
            store="app_store",
            plan_code=plan_code,
            period_code=period_code,
            product_id=f"net.vipe.aionex.{suffix}",
            active=True,
        )
        assert created["status"] == "active"
        overview = await billing.owner_store_overview(session)
        assert any(item["id"] == created["id"] for item in overview["mappings"])
        assert not any(
            item.get("code") == "unmapped_price"
            and item.get("store") == "app_store"
            and item.get("plan_code") == plan_code
            and item.get("period_code") == period_code
            for item in overview["diagnostics"]
        )

        disabled = await billing.owner_set_store_mapping_status(
            session, mapping_id=created["id"], active=False
        )
        assert disabled["status"] == "inactive"
        overview = await billing.owner_store_overview(session)
        assert any(
            item.get("code") == "unmapped_price"
            and item.get("store") == "app_store"
            and item.get("plan_code") == plan_code
            and item.get("period_code") == period_code
            for item in overview["diagnostics"]
        )
