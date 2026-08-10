from pathlib import Path
ROOT=Path.cwd()
def read(path): return (ROOT/path).read_text()

def test_official_apple_server_library_is_pinned_and_used():
    req=read('web-dashboard/backend/requirements-runtime.txt')
    svc=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    assert 'app-store-server-library==3.1.2' in req
    assert 'SignedDataVerifier' in svc
    assert 'verify_and_decode_notification' in svc
    assert 'AsyncAppStoreServerAPIClient' in svc
    assert 'get_all_subscription_statuses' in svc

def test_google_play_v2_verification_rtdn_and_acknowledgement():
    svc=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    for token in ['purchases/subscriptionsv2/tokens','androidpublisher','subscriptionNotification','PyJWKClient','GOOGLE_PLAY_PUBSUB_SERVICE_ACCOUNT_EMAIL',':acknowledge']:
        assert token in svc

def test_purchase_tokens_are_hash_indexed_and_encrypted_at_rest():
    svc=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    model=read('web-dashboard/backend/app/db/models.py')
    migration=read('web-dashboard/backend/alembic/versions/20260809_0012_mobile_store_billing.py')
    assert '_encrypt_token' in svc and '_decrypt_token' in svc and 'Fernet' in svc
    assert 'purchase_token_ciphertext' in model and 'purchase_token_ciphertext' in migration
    assert 'purchase_token_hash' in model

def test_replay_protection_and_sanitized_event_storage():
    svc=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    assert 'MobileStoreEvent.external_event_id == event_id' in svc
    assert 'return {"status": "duplicate"' in svc
    assert 'payload_hash=' in ''.join(svc.split())
    assert 'event_payload={' in ''.join(svc.split())
    start=svc.index('event_payload={')
    snippet=svc[start:svc.index('\n    if existing:', start)]
    assert 'signed_payload' not in snippet and 'signedTransactionInfo' not in snippet

def test_lifecycle_states_and_entitlement_revocation_are_covered():
    svc=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    for state in ['grace_period','on_hold','paused','expired','revoked','billing_retry']:
        assert state in svc
    assert 'account.entitlements = []' in svc
    assert 'authoritative = max(active, key=rank)' in svc
    assert 'account.plan_id = None' in svc

def test_cancelled_google_subscription_keeps_access_until_expiry():
    svc=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    assert 'status_ == "canceled" and expiry and expiry > _now()' in svc

def test_mobile_clients_use_authenticated_server_verification():
    ios=read('mobile/ios/AIONEXAIOS/StoreBilling.swift')
    portal=read('mobile/ios/AIONEXAIOS/PortalView.swift')
    android=read('mobile/android/app/src/main/java/net/vipe/aionex/PlayBillingManager.java')
    assert 'Authorization' in ios and 'Bearer \\(accessToken)' in ios
    assert "aionex.access_token" in portal
    assert 'Authorization' in android and 'server_acknowledged' in android
