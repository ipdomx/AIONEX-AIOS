from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2]
def read(p): return (ROOT/p).read_text()

def test_owner_mapping_api_and_diagnostics_exist():
    svc=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    api=read('web-dashboard/backend/app/api/v1/endpoints/mobile_store_billing.py')
    for token in ['owner_store_overview','owner_upsert_store_mapping','owner_set_store_mapping_status','unmapped_price','provider_not_configured']:
        assert token in svc
    for token in ['@router.get("/owner/overview")','@router.post("/owner/mappings")','@router.patch("/owner/mappings/{mapping_id}")','require_super_owner']:
        assert token in api

def test_single_account_entitlement_authority_across_providers():
    svc=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    assert 'Multiple providers may represent the same customer' in svc
    assert 'entitlement_source' in svc
    assert 'authoritative = max(active, key=rank)' in svc
    assert 'BillingSubscription.status.in_(["active", "trialing", "grace_period"])' in svc

def test_user_subscription_has_source_and_store_management_urls():
    billing=read('web-dashboard/backend/app/services/billing.py')
    assert '"source": "mobile_store"' in billing
    assert 'https://apps.apple.com/account/subscriptions' in billing
    assert 'https://play.google.com/store/account/subscriptions?package=' in billing
    ui=read('vip-frontend/src/components/pages/billing-client.tsx')
    assert 'sourceMobileStore' in ui and 'manageStoreSubscription' in ui
    assert 'summary.subscription.source !== "mobile_store"' in ui

def test_owner_dashboard_exposes_mobile_store_control():
    page=read('web-dashboard/frontend/src/app/owner/billing/page.tsx')
    api=read('web-dashboard/frontend/src/lib/billing-api.ts')
    assert '["stores", "Mobile stores"]' in page
    assert 'Plan ↔ store product mapping' in page
    assert 'Readiness diagnostics' in page
    assert 'saveMobileStoreMapping' in api and 'setMobileStoreMappingStatus' in api

def test_six_portal_languages_have_store_subscription_copy():
    for lang in ['ar','en','fr','de','es','tr']:
        data=json.loads((ROOT/f'vip-frontend/src/messages/{lang}.json').read_text())['billing']
        for key in ['sourceMobileStore','sourceWeb','manageStoreSubscription','restorePurchases']:
            assert data[key]

def test_native_clients_have_localized_restore_and_manage_subscription():
    ios=read('mobile/ios/AIONEXAIOS/SubscriptionView.swift')
    android=read('mobile/android/app/src/main/java/net/vipe/aionex/PlayBillingManager.java')
    for lang in ['"en"','"ar"','"fr"','"de"','"es"','"tr"']:
        assert lang in ios
        assert lang in android
    assert 'https://apps.apple.com/account/subscriptions' in ios
    assert 'https://play.google.com/store/account/subscriptions?package=' in android
