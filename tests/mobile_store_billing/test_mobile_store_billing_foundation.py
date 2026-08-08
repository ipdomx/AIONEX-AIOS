from pathlib import Path
ROOT=Path.cwd()

def read(path): return (ROOT/path).read_text()

def test_mobile_store_contract_and_routes_exist():
    service=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    endpoint=read('web-dashboard/backend/app/api/v1/endpoints/mobile_store_billing.py')
    router=read('web-dashboard/backend/app/api/v1/router.py')
    migration=read('web-dashboard/backend/alembic/versions/20260809_0012_mobile_store_billing.py')
    assert 'StoreName = Literal["app_store", "google_play"]' in service
    for route in ['/verify','/restore/{store}','/reconcile/{store}','/notifications/app-store','/notifications/google-play']:
        assert route in endpoint
    assert 'prefix="/billing/mobile-store"' in router
    for table in ['mobile_store_products','mobile_store_purchases','mobile_store_events']:
        assert table in migration

def test_entitlements_only_follow_authoritative_verification():
    service=read('web-dashboard/backend/app/services/mobile_store_billing.py')
    assert 'verify_and_decode_signed_transaction' in service
    assert '_google_get_subscription' in service
    assert 'purchase.verified=True' in service
    assert 'await _sync_entitlements' in service
    assert service.index('purchase.verified=True') < service.index('await _sync_entitlements')

def test_mobile_store_secrets_are_server_side_only():
    config=read('web-dashboard/backend/app/core/config.py')
    for key in ['APP_STORE_PRIVATE_KEY','GOOGLE_PLAY_SERVICE_ACCOUNT_JSON','APP_STORE_ROOT_CERTIFICATES_DIR','GOOGLE_PLAY_PUBSUB_AUDIENCE']:
        assert key in config
    ios='\n'.join(p.read_text(errors='ignore') for p in (ROOT/'mobile/ios').rglob('*.swift'))
    android='\n'.join(p.read_text(errors='ignore') for p in (ROOT/'mobile/android/app/src').rglob('*') if p.is_file())
    assert 'APP_STORE_PRIVATE_KEY' not in ios
    assert 'GOOGLE_PLAY_SERVICE_ACCOUNT_JSON' not in android
