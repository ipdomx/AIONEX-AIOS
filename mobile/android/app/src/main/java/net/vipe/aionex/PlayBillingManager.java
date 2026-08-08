package net.vipe.aionex;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebView;
import android.widget.Toast;

import com.android.billingclient.api.AcknowledgePurchaseParams;
import com.android.billingclient.api.BillingClient;
import com.android.billingclient.api.BillingClientStateListener;
import com.android.billingclient.api.BillingFlowParams;
import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.PendingPurchasesParams;
import com.android.billingclient.api.ProductDetails;
import com.android.billingclient.api.ProductDetailsResponseListener;
import com.android.billingclient.api.Purchase;
import com.android.billingclient.api.PurchasesUpdatedListener;
import com.android.billingclient.api.QueryProductDetailsParams;
import com.android.billingclient.api.QueryProductDetailsResult;
import com.android.billingclient.api.QueryPurchasesParams;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Google Play Billing client. The server remains authoritative for entitlements. */
public final class PlayBillingManager implements PurchasesUpdatedListener {
    private static final String API_BASE = "https://ai.vip-e.net/api/v1/billing/mobile-store/";
    private final Activity activity;
    private final WebView webView;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final BillingClient billingClient;
    private final Map<String, StoreProductRecord> records = new HashMap<>();
    private final Map<String, ProductDetails> details = new HashMap<>();
    private String accessToken;
    private boolean started;

    public PlayBillingManager(Activity activity, WebView webView) {
        this.activity = activity;
        this.webView = webView;
        PendingPurchasesParams pending = PendingPurchasesParams.newBuilder()
                .enableOneTimeProducts()
                .enablePrepaidPlans()
                .build();
        billingClient = BillingClient.newBuilder(activity)
                .setListener(this)
                .enablePendingPurchases(pending)
                .enableAutoServiceReconnection()
                .build();
    }

    public void start() {
        if (started) return;
        started = true;
        billingClient.startConnection(new BillingClientStateListener() {
            @Override public void onBillingSetupFinished(BillingResult result) {
                if (result.getResponseCode() == BillingClient.BillingResponseCode.OK) {
                    restorePurchases(false);
                }
            }
            @Override public void onBillingServiceDisconnected() { /* auto reconnect enabled */ }
        });
    }

    public void openSubscriptionUi() {
        readAccessToken(token -> {
            if (token == null || token.isEmpty()) {
                toast(copy("signin"));
                return;
            }
            accessToken = token;
            fetchCatalogueAndProducts();
        });
    }

    public void restorePurchases(boolean userInitiated) {
        if (!billingClient.isReady()) {
            if (userInitiated) toast(copy("reconnecting"));
            return;
        }
        readAccessToken(token -> {
            if (token == null || token.isEmpty()) {
                if (userInitiated) toast(copy("signin"));
                return;
            }
            accessToken = token;
            QueryPurchasesParams params = QueryPurchasesParams.newBuilder()
                    .setProductType(BillingClient.ProductType.SUBS)
                    .build();
            billingClient.queryPurchasesAsync(params, (result, purchases) -> {
                if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                    if (userInitiated) toast(copy("query_failed"));
                    return;
                }
                for (Purchase purchase : purchases) processPurchase(purchase);
                if (userInitiated) toast(copy("restore_submitted"));
            });
        });
    }

    private void fetchCatalogueAndProducts() {
        network.execute(() -> {
            try {
                JSONArray array = new JSONArray(api("catalog/google_play", "GET", null));
                records.clear();
                List<QueryProductDetailsParams.Product> products = new ArrayList<>();
                for (int i = 0; i < array.length(); i++) {
                    JSONObject item = array.getJSONObject(i);
                    StoreProductRecord record = StoreProductRecord.from(item);
                    records.put(record.productId, record);
                    products.add(QueryProductDetailsParams.Product.newBuilder()
                            .setProductId(record.productId)
                            .setProductType(BillingClient.ProductType.SUBS)
                            .build());
                }
                main.post(() -> { queryProductDetails(products); restorePurchases(false); });
            } catch (Exception error) {
                toast(copy("catalog_failed"));
            }
        });
    }

    private void queryProductDetails(List<QueryProductDetailsParams.Product> products) {
        if (!billingClient.isReady()) { toast(copy("not_ready")); return; }
        if (products.isEmpty()) { toast(copy("none_configured")); return; }
        QueryProductDetailsParams params = QueryProductDetailsParams.newBuilder()
                .setProductList(products).build();
        billingClient.queryProductDetailsAsync(params, new ProductDetailsResponseListener() {
            @Override public void onProductDetailsResponse(BillingResult result, QueryProductDetailsResult response) {
                if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                    toast(copy("details_failed")); return;
                }
                details.clear();
                for (ProductDetails detail : response.getProductDetailsList()) details.put(detail.getProductId(), detail);
                showProducts();
            }
        });
    }

    private void showProducts() {
        List<ProductDetails> items = new ArrayList<>(details.values());
        if (items.isEmpty()) { toast(copy("none_eligible")); return; }
        String[] labels = new String[items.size() + 1];
        for (int i = 0; i < items.size(); i++) labels[i] = label(items.get(i));
        labels = java.util.Arrays.copyOf(labels, items.size() + 2);
        labels[items.size()] = copy("restore");
        labels[items.size() + 1] = copy("manage");
        new AlertDialog.Builder(activity)
                .setTitle(copy("title"))
                .setItems(labels, (dialog, which) -> {
                    if (which == items.size()) restorePurchases(true);
                    else if (which == items.size() + 1) {
                        android.net.Uri uri = android.net.Uri.parse("https://play.google.com/store/account/subscriptions?package=" + activity.getPackageName().replace(".debug", ""));
                        activity.startActivity(new android.content.Intent(android.content.Intent.ACTION_VIEW, uri));
                    } else launch(items.get(which));
                })
                .setNegativeButton(copy("cancel"), null)
                .show();
    }

    private String label(ProductDetails detail) {
        ProductDetails.SubscriptionOfferDetails offer = selectOffer(detail);
        String price = "";
        if (offer != null && !offer.getPricingPhases().getPricingPhaseList().isEmpty()) {
            List<ProductDetails.PricingPhase> phases = offer.getPricingPhases().getPricingPhaseList();
            price = phases.get(phases.size() - 1).getFormattedPrice();
        }
        return detail.getName() + (price.isEmpty() ? "" : " — " + price);
    }

    private ProductDetails.SubscriptionOfferDetails selectOffer(ProductDetails detail) {
        List<ProductDetails.SubscriptionOfferDetails> offers = detail.getSubscriptionOfferDetails();
        if (offers == null || offers.isEmpty()) return null;
        StoreProductRecord record = records.get(detail.getProductId());
        if (record != null) {
            for (ProductDetails.SubscriptionOfferDetails offer : offers) {
                boolean baseMatches = record.basePlanId == null || record.basePlanId.equals(offer.getBasePlanId());
                boolean offerMatches = record.offerId == null || record.offerId.equals(offer.getOfferId());
                if (baseMatches && offerMatches) return offer;
            }
        }
        return offers.get(0);
    }

    private void launch(ProductDetails detail) {
        ProductDetails.SubscriptionOfferDetails offer = selectOffer(detail);
        if (offer == null) { toast(copy("none_eligible")); return; }
        BillingFlowParams.ProductDetailsParams product = BillingFlowParams.ProductDetailsParams.newBuilder()
                .setProductDetails(detail)
                .setOfferToken(offer.getOfferToken())
                .build();
        BillingFlowParams params = BillingFlowParams.newBuilder()
                .setProductDetailsParamsList(java.util.Collections.singletonList(product))
                .build();
        BillingResult result = billingClient.launchBillingFlow(activity, params);
        if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
            toast(copy("launch_failed"));
        }
    }

    @Override public void onPurchasesUpdated(BillingResult result, List<Purchase> purchases) {
        if (result.getResponseCode() == BillingClient.BillingResponseCode.OK && purchases != null) {
            for (Purchase purchase : purchases) processPurchase(purchase);
        } else if (result.getResponseCode() != BillingClient.BillingResponseCode.USER_CANCELED) {
            toast(copy("purchase_failed"));
        }
    }

    private void processPurchase(Purchase purchase) {
        if (purchase.getPurchaseState() != Purchase.PurchaseState.PURCHASED) return;
        String productId = purchase.getProducts().isEmpty() ? null : purchase.getProducts().get(0);
        StoreProductRecord record = productId == null ? null : records.get(productId);
        if (record == null) {
            // Refresh mapping before submitting restored/out-of-app purchases.
            fetchCatalogueAndProducts();
            return;
        }
        network.execute(() -> {
            try {
                JSONObject body = new JSONObject()
                        .put("store", "google_play")
                        .put("product_record_id", record.id)
                        .put("purchase_token", purchase.getPurchaseToken());
                JSONObject response = new JSONObject(api("verify", "POST", body.toString()));
                // Acknowledge only after the authoritative AIOS server confirms verification.
                if (response.optBoolean("verified", false) && !response.optBoolean("server_acknowledged", false) && !purchase.isAcknowledged()) {
                    main.post(() -> acknowledge(purchase));
                }
            } catch (Exception ignored) {
                // Batch 4 activates verification. Fail closed: never acknowledge or grant locally.
            }
        });
    }

    private void acknowledge(Purchase purchase) {
        AcknowledgePurchaseParams params = AcknowledgePurchaseParams.newBuilder()
                .setPurchaseToken(purchase.getPurchaseToken()).build();
        billingClient.acknowledgePurchase(params, result -> {
            if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                toast(copy("ack_retry"));
            }
        });
    }

    private void readAccessToken(TokenCallback callback) {
        webView.evaluateJavascript("window.localStorage.getItem('aionex.access_token')", raw -> {
            if (raw == null || "null".equals(raw)) { callback.accept(null); return; }
            try { callback.accept(new JSONArray("[" + raw + "]").getString(0)); }
            catch (JSONException error) { callback.accept(null); }
        });
    }

    private String api(String path, String method, String body) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(API_BASE + path).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Authorization", "Bearer " + accessToken);
        if (body != null) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            try (OutputStream out = connection.getOutputStream()) { out.write(body.getBytes(StandardCharsets.UTF_8)); }
        }
        int code = connection.getResponseCode();
        InputStream stream = code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream();
        StringBuilder result = new StringBuilder();
        if (stream != null) try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line; while ((line = reader.readLine()) != null) result.append(line);
        }
        connection.disconnect();
        if (code < 200 || code >= 300) throw new IllegalStateException("AIOS billing HTTP " + code);
        return result.toString();
    }

    private String copy(String key) {
        String language = Locale.getDefault().getLanguage();
        Map<String, String[]> values = new HashMap<>();
        values.put("en", new String[]{"AIONEX Subscription","Restore purchases","Manage in Google Play","Sign in to AIONEX before subscribing.","Google Play Billing is reconnecting. Try again shortly.","Unable to query Google Play purchases.","Restore submitted for server verification.","Unable to load AIONEX subscription catalogue.","Google Play Billing is not ready.","No Google Play subscriptions are configured.","Unable to load Google Play subscription details.","No eligible Google Play subscription offers are available.","Cancel","Google Play could not start the subscription flow.","Google Play purchase did not complete.","Purchase verified; acknowledgement will be retried."});
        values.put("ar", new String[]{"اشتراك AIONEX","استعادة المشتريات","إدارة الاشتراك في Google Play","سجّل الدخول إلى AIONEX قبل الاشتراك.","جارٍ إعادة الاتصال بخدمة Google Play.","تعذر الاستعلام عن مشتريات Google Play.","تم إرسال الاستعادة للتحقق من الخادم.","تعذر تحميل كتالوج اشتراكات AIONEX.","خدمة Google Play Billing غير جاهزة.","لا توجد اشتراكات Google Play مهيأة.","تعذر تحميل تفاصيل الاشتراك.","لا توجد عروض اشتراك مؤهلة.","إلغاء","تعذر بدء عملية الاشتراك.","لم تكتمل عملية الشراء.","تم التحقق من الشراء وستتم إعادة محاولة التأكيد."});
        values.put("fr", new String[]{"Abonnement AIONEX","Restaurer les achats","Gérer dans Google Play","Connectez-vous à AIONEX avant de vous abonner.","Reconnexion à Google Play Billing.","Impossible de consulter les achats Google Play.","Restauration envoyée pour vérification serveur.","Impossible de charger le catalogue AIONEX.","Google Play Billing n’est pas prêt.","Aucun abonnement Google Play configuré.","Impossible de charger les détails.","Aucune offre éligible.","Annuler","Impossible de démarrer l’abonnement.","L’achat n’a pas abouti.","Achat vérifié ; la confirmation sera réessayée."});
        values.put("de", new String[]{"AIONEX-Abonnement","Käufe wiederherstellen","In Google Play verwalten","Melden Sie sich vor dem Abonnieren bei AIONEX an.","Google Play Billing wird erneut verbunden.","Google-Play-Käufe konnten nicht abgefragt werden.","Wiederherstellung zur Serverprüfung gesendet.","AIONEX-Katalog konnte nicht geladen werden.","Google Play Billing ist nicht bereit.","Keine Google-Play-Abonnements konfiguriert.","Abonnementdetails konnten nicht geladen werden.","Keine geeigneten Angebote verfügbar.","Abbrechen","Abonnement konnte nicht gestartet werden.","Kauf wurde nicht abgeschlossen.","Kauf verifiziert; Bestätigung wird erneut versucht."});
        values.put("es", new String[]{"Suscripción AIONEX","Restaurar compras","Gestionar en Google Play","Inicia sesión en AIONEX antes de suscribirte.","Reconectando Google Play Billing.","No se pudieron consultar las compras.","Restauración enviada para verificación.","No se pudo cargar el catálogo AIONEX.","Google Play Billing no está listo.","No hay suscripciones configuradas.","No se pudieron cargar los detalles.","No hay ofertas elegibles.","Cancelar","No se pudo iniciar la suscripción.","La compra no se completó.","Compra verificada; se reintentará la confirmación."});
        values.put("tr", new String[]{"AIONEX Aboneliği","Satın alımları geri yükle","Google Play’de yönet","Abone olmadan önce AIONEX’e giriş yapın.","Google Play Billing yeniden bağlanıyor.","Satın alımlar sorgulanamadı.","Geri yükleme sunucu doğrulamasına gönderildi.","AIONEX kataloğu yüklenemedi.","Google Play Billing hazır değil.","Google Play aboneliği yapılandırılmamış.","Abonelik ayrıntıları yüklenemedi.","Uygun teklif yok.","İptal","Abonelik akışı başlatılamadı.","Satın alma tamamlanmadı.","Satın alma doğrulandı; onay yeniden denenecek."});
        String[] v = values.getOrDefault(language, values.get("en"));
        String[] keys = {"title","restore","manage","signin","reconnecting","query_failed","restore_submitted","catalog_failed","not_ready","none_configured","details_failed","none_eligible","cancel","launch_failed","purchase_failed","ack_retry"};
        for (int i = 0; i < keys.length; i++) if (keys[i].equals(key)) return v[i];
        return key;
    }

    private void toast(String message) { main.post(() -> Toast.makeText(activity, message, Toast.LENGTH_LONG).show()); }
    public void close() { billingClient.endConnection(); network.shutdownNow(); }
    private interface TokenCallback { void accept(String token); }

    private static final class StoreProductRecord {
        final String id, productId, basePlanId, offerId;
        StoreProductRecord(String id, String productId, String basePlanId, String offerId) {
            this.id = id; this.productId = productId; this.basePlanId = basePlanId; this.offerId = offerId;
        }
        static StoreProductRecord from(JSONObject item) throws JSONException {
            return new StoreProductRecord(item.getString("id"), item.getString("product_id"),
                    nullable(item, "base_plan_id"), nullable(item, "offer_id"));
        }
        private static String nullable(JSONObject object, String key) {
            return object.isNull(key) ? null : object.optString(key, null);
        }
    }
}
