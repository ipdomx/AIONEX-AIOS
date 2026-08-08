from pathlib import Path


def test_mobile_store_contract_files_and_routes() -> None:
    root = Path.cwd()
    service = (root / "web-dashboard/backend/app/services/mobile_store_billing.py").read_text()
    endpoint = (root / "web-dashboard/backend/app/api/v1/endpoints/mobile_store_billing.py").read_text()
    router = (root / "web-dashboard/backend/app/api/v1/router.py").read_text()
    migration = (root / "web-dashboard/backend/alembic/versions/20260809_0012_mobile_store_billing.py").read_text()
    assert 'StoreName = Literal["app_store", "google_play"]' in service
    assert 'server_verification_required' in service
    assert 'status.HTTP_503_SERVICE_UNAVAILABLE' in service
    assert '@router.post("/verify")' in endpoint
    assert '@router.post("/restore/{store}")' in endpoint
    assert 'prefix="/billing/mobile-store"' in router
    assert 'mobile_store_products' in migration
    assert 'mobile_store_purchases' in migration
    assert 'mobile_store_events' in migration


def test_clients_cannot_grant_entitlements_from_assertion() -> None:
    root = Path.cwd()
    service = (root / "web-dashboard/backend/app/services/mobile_store_billing.py").read_text()
    assert 'verified=False' in service
    assert 'pending_verification' in service
    assert 'Fail closed' in service
    assert 'BillingAccount' not in service
    assert 'entitlements =' not in service


def test_mobile_store_secrets_are_configured_server_side_only() -> None:
    root = Path.cwd()
    config = (root / "web-dashboard/backend/app/core/config.py").read_text()
    assert 'APP_STORE_PRIVATE_KEY' in config
    assert 'GOOGLE_PLAY_SERVICE_ACCOUNT_JSON' in config
    ios_files = "\n".join(p.read_text(errors="ignore") for p in (root / "mobile/ios").rglob("*.swift"))
    android_files = "\n".join(p.read_text(errors="ignore") for p in (root / "mobile/android/app/src").rglob("*.*") if p.is_file())
    assert 'APP_STORE_PRIVATE_KEY' not in ios_files
    assert 'GOOGLE_PLAY_SERVICE_ACCOUNT_JSON' not in android_files
