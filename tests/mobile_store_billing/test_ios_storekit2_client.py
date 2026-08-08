from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def read(rel): return (ROOT / rel).read_text()

def test_storekit2_purchase_restore_listener_and_server_submission():
    s=read('mobile/ios/AIONEXAIOS/StoreBilling.swift')
    for token in ['import StoreKit','Product.products','product.purchase()','AppStore.sync()','Transaction.currentEntitlements','Transaction.updates','jwsRepresentation','await transaction.finish()','/api/v1/billing/mobile-store']:
        assert token in s

def test_native_subscription_ui_exists():
    s=read('mobile/ios/AIONEXAIOS/SubscriptionView.swift')
    assert 'Restore Purchases' in s and 'billing.purchase(product)' in s

def test_portal_intercepts_digital_billing_to_native_storekit():
    s=read('mobile/ios/AIONEXAIOS/PortalView.swift')
    assert 'nativeBillingPaths' in s and 'aionexShowNativeSubscription' in s
    assert '["/billing", "/pricing"]' in s

def test_app_presents_native_subscription_sheet():
    s=read('mobile/ios/AIONEXAIOS/AIONEXAIOSApp.swift')
    assert 'SubscriptionView()' in s and '.sheet(isPresented:' in s

def test_ios_does_not_embed_store_secrets_or_stripe_purchase_code():
    allsrc='\n'.join(p.read_text(errors='ignore') for p in (ROOT/'mobile/ios/AIONEXAIOS').rglob('*.swift'))
    for forbidden in ['APP_STORE_PRIVATE_KEY','STRIPE_SECRET_KEY','sk_live_','sk_test_','checkout.stripe.com']:
        assert forbidden not in allsrc
