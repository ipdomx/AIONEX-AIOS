from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
def read(rel): return (ROOT / rel).read_text()

def test_current_play_billing_library_is_pinned():
    gradle=read('mobile/android/app/build.gradle')
    assert 'billing_version = "9.1.0"' in gradle
    assert 'com.android.billingclient:billing:$billing_version' in gradle

def test_subscription_product_offer_and_purchase_flow():
    s=read('mobile/android/app/src/main/java/net/vipe/aionex/PlayBillingManager.java')
    for token in ['BillingClient.ProductType.SUBS','queryProductDetailsAsync','getSubscriptionOfferDetails','getBasePlanId()','getOfferId()','setOfferToken','launchBillingFlow','PurchasesUpdatedListener']:
        assert token in s

def test_restore_pending_and_server_verification_flow():
    s=read('mobile/android/app/src/main/java/net/vipe/aionex/PlayBillingManager.java')
    for token in ['enablePendingPurchases','queryPurchasesAsync','Purchase.PurchaseState.PURCHASED','purchase_token','/api/v1/billing/mobile-store/','response.optBoolean("verified", false)']:
        assert token in s

def test_acknowledgement_is_gated_by_authoritative_server_verification():
    s=read('mobile/android/app/src/main/java/net/vipe/aionex/PlayBillingManager.java')
    gate=s.index('response.optBoolean("verified", false)')
    ack=s.index('acknowledge(purchase)', gate)
    assert ack > gate
    assert 'never acknowledge or grant locally' in s

def test_android_portal_routes_digital_subscription_to_native_billing():
    s=read('mobile/android/app/src/main/java/net/vipe/aionex/MainActivity.java')
    assert 'playBilling.openSubscriptionUi()' in s
    assert 'path.contains("/billing") || path.contains("/pricing")' in s

def test_no_store_or_stripe_secrets_embedded():
    src='\n'.join(p.read_text(errors='ignore') for p in (ROOT/'mobile/android/app/src/main').rglob('*') if p.is_file())
    for forbidden in ['GOOGLE_PLAY_SERVICE_ACCOUNT_JSON','STRIPE_SECRET_KEY','sk_live_','sk_test_']:
        assert forbidden not in src
