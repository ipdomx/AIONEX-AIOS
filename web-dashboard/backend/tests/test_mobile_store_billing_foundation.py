from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services import mobile_store_billing as billing


def test_google_state_normalization_keeps_cancelled_access_until_expiry():
    future=(datetime.now(timezone.utc)+timedelta(days=10)).isoformat().replace('+00:00','Z')
    payload={
        'subscriptionState':'SUBSCRIPTION_STATE_CANCELED',
        'startTime':'2026-08-01T00:00:00Z',
        'acknowledgementState':'ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED',
        'lineItems':[{'productId':'pro.monthly','expiryTime':future,'autoRenewingPlan':{'autoRenewEnabled':False}}],
    }
    result=billing._normalize_google(payload)
    assert result['status']=='active'
    assert result['auto_renewing'] is False


def test_google_grace_and_hold_states_are_distinct():
    base={'startTime':'2026-08-01T00:00:00Z','lineItems':[{'productId':'pro.monthly','expiryTime':'2026-09-01T00:00:00Z'}]}
    grace=billing._normalize_google({**base,'subscriptionState':'SUBSCRIPTION_STATE_IN_GRACE_PERIOD'})
    hold=billing._normalize_google({**base,'subscriptionState':'SUBSCRIPTION_STATE_ON_HOLD'})
    assert grace['status']=='grace_period'
    assert hold['status']=='on_hold'


def test_google_tokens_are_encrypted_and_hashable_without_plaintext_storage():
    token='test-purchase-token-sensitive'
    ciphertext=billing._encrypt_token(token)
    assert token not in ciphertext
    assert billing._decrypt_token(ciphertext)==token
    assert len(billing._token_hash(token))==64


def test_store_callback_and_reconciliation_routes_are_registered():
    root=Path(__file__).resolve().parents[1]
    endpoint=(root/'app/api/v1/endpoints/mobile_store_billing.py').read_text()
    router=(root/'app/api/v1/router.py').read_text()
    assert '@router.post("/notifications/app-store"' in endpoint
    assert '@router.post("/notifications/google-play"' in endpoint
    assert '@router.post("/reconcile/{store}")' in endpoint
    assert 'prefix="/billing/mobile-store"' in router


def test_official_apple_verifier_dependency_imports():
    from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
    from appstoreserverlibrary.api_client import AsyncAppStoreServerAPIClient
    assert SignedDataVerifier and AsyncAppStoreServerAPIClient


def test_migration_persists_replay_events_and_encrypted_google_token():
    root=Path(__file__).resolve().parents[1]
    migration=(root/'alembic/versions/20260809_0012_mobile_store_billing.py').read_text()
    assert 'mobile_store_events' in migration
    assert 'purchase_token_ciphertext' in migration
    assert 'uq_mobile_store_event_external' in migration
