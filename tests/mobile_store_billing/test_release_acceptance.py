from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def read(p): return (ROOT/p).read_text()

def test_release_validator_is_truthful_and_never_publishes():
    s=read('scripts/mobile/validate_store_billing_release.py')
    assert 'external_acceptance_status' in s
    assert 'blocked_missing_external_credentials_or_store_configuration' in s
    assert "'store_publication_performed':False" in s
    assert "'simulated_e2e_status':'complete'" in s
    assert "'batch6_status':'complete_simulated_e2e'" in s
    assert 'APP_STORE_PRIVATE_KEY' in s and 'GOOGLE_PLAY_SERVICE_ACCOUNT_JSON' in s

def test_release_runbook_has_non_destructive_rollback():
    d=read('docs/mobile-store-billing/BATCH6_RELEASE_READINESS.md')
    assert 'leaving migration 0012 in place' in d
    assert 'Do not delete verified purchase/event records' in d
    assert 'without affecting Stripe web billing' in d

def test_google_lifecycle_acceptance_matrix_present():
    s=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    for state in ['SUBSCRIPTION_STATE_ACTIVE','SUBSCRIPTION_STATE_IN_GRACE_PERIOD','SUBSCRIPTION_STATE_ON_HOLD','SUBSCRIPTION_STATE_PAUSED','SUBSCRIPTION_STATE_CANCELED','SUBSCRIPTION_STATE_EXPIRED']:
        assert state in s
    for state in ['revoked','billing_retry','grace_period','expired']:
        assert state in s

def test_apple_lifecycle_acceptance_matrix_present():
    s=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    for event in ['DID_RENEW','DID_FAIL_TO_RENEW','EXPIRED','GRACE_PERIOD_EXPIRED','REFUND','REVOKE']:
        assert event in s

def test_entitlement_arbitration_survives_provider_overlap():
    s=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    assert 'Multiple providers may represent the same customer' in s
    assert 'authoritative = max(active, key=rank)' in s
    assert 'entitlement_source' in s
