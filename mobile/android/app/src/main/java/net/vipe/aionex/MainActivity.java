package net.vipe.aionex;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.MimeTypeMap;
import android.webkit.SafeBrowsingResponse;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

public final class MainActivity extends Activity {
    private static final String PORTAL_HOST = "ai.vip-e.net";
    private static final String PORTAL_URL = "https://" + PORTAL_HOST + "/ar/";
    private static final String ASSET_HOST = "appassets.aionex.local";
    private static final String OFFLINE_URL = "https://" + ASSET_HOST + "/offline.html";
    private WebView webView;
    private PlayBillingManager playBilling;
    private boolean showingOfflineFallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(3, 5, 10));
        getWindow().setNavigationBarColor(Color.rgb(3, 5, 10));

        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(3, 5, 10));
        configureWebView(webView);
        setContentView(webView);
        playBilling = new PlayBillingManager(this, webView);
        playBilling.start();
        webView.loadUrl(resolveLaunchUrl(getIntent()));
    }

    private String resolveLaunchUrl(Intent intent) {
        Uri uri = intent == null ? null : intent.getData();
        if (uri == null || !"https".equalsIgnoreCase(uri.getScheme()) ||
                !PORTAL_HOST.equalsIgnoreCase(uri.getHost())) {
            return PORTAL_URL;
        }
        String path = uri.getEncodedPath();
        if (path == null || path.isEmpty() || !isSafePath(path)) return PORTAL_URL;
        if (!path.endsWith("/") && !path.contains(".")) path += "/";
        return "https://" + PORTAL_HOST + path;
    }

    private void configureWebView(WebView view) {
        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSafeBrowsingEnabled(true);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(view, false);

        view.setWebChromeClient(new WebChromeClient());
        view.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(
                    WebView currentView,
                    WebResourceRequest request
            ) {
                Uri uri = request.getUrl();
                if (!"https".equalsIgnoreCase(uri.getScheme()) ||
                        !ASSET_HOST.equalsIgnoreCase(uri.getHost())) return null;
                return assetResponse(uri.getEncodedPath());
            }

            @Override
            public boolean shouldOverrideUrlLoading(
                    WebView currentView,
                    WebResourceRequest request
            ) {
                Uri uri = request.getUrl();
                if (!"https".equalsIgnoreCase(uri.getScheme())) return true;
                String host = uri.getHost();
                if (PORTAL_HOST.equalsIgnoreCase(host)) {
                    String path = uri.getPath();
                    if (path != null && (path.contains("/billing") || path.contains("/pricing"))) {
                        if (playBilling != null) playBilling.openSubscriptionUi();
                        return true;
                    }
                    return false;
                }
                if (ASSET_HOST.equalsIgnoreCase(host)) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
                return true;
            }

            @Override
            public void onPageFinished(WebView currentView, String url) {
                super.onPageFinished(currentView, url);
                if (url != null && url.startsWith("https://" + PORTAL_HOST + "/")) {
                    showingOfflineFallback = false;
                }
            }

            @Override
            public void onReceivedError(
                    WebView currentView,
                    WebResourceRequest request,
                    WebResourceError error
            ) {
                if (request.isForMainFrame()) showOfflineFallback();
            }

            @Override
            public void onReceivedHttpError(
                    WebView currentView,
                    WebResourceRequest request,
                    WebResourceResponse errorResponse
            ) {
                if (request.isForMainFrame() && errorResponse.getStatusCode() >= 500) {
                    showOfflineFallback();
                }
            }

            @Override
            public void onSafeBrowsingHit(
                    WebView currentView,
                    WebResourceRequest request,
                    int threatType,
                    SafeBrowsingResponse callback
            ) {
                callback.backToSafety(true);
            }
        });
    }

    private void showOfflineFallback() {
        if (webView == null || showingOfflineFallback) return;
        showingOfflineFallback = true;
        webView.loadUrl(OFFLINE_URL);
    }

    private WebResourceResponse assetResponse(String encodedPath) {
        String path = encodedPath == null ? "/offline.html" : Uri.decode(encodedPath);
        if (!isSafePath(path)) return response("text/plain", "UTF-8", null, 404);
        if (path.endsWith("/")) path += "index.html";
        String assetPath = "www" + path;
        try {
            return response(mimeType(path), "UTF-8", getAssets().open(assetPath), 200);
        } catch (IOException ignored) {
            try {
                return response("text/html", "UTF-8", getAssets().open("www/offline.html"), 404);
            } catch (IOException unavailable) {
                return response("text/plain", "UTF-8", null, 404);
            }
        }
    }

    private WebResourceResponse response(
            String mime,
            String encoding,
            InputStream stream,
            int status
    ) {
        Map<String, String> headers = new HashMap<>();
        headers.put("Cache-Control", status == 200 ? "public, max-age=86400" : "no-store");
        headers.put("X-Content-Type-Options", "nosniff");
        headers.put("Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
                "font-src 'self' data:; script-src 'self' 'unsafe-inline'; object-src 'none'; " +
                "frame-ancestors 'none'; connect-src https://api.vip-e.net");
        WebResourceResponse response = new WebResourceResponse(mime, encoding, stream);
        response.setStatusCodeAndReasonPhrase(status, status == 200 ? "OK" : "Not Found");
        response.setResponseHeaders(headers);
        return response;
    }

    private boolean isSafePath(String path) {
        return path.startsWith("/") && !path.contains("..") && !path.contains("\\") &&
                path.indexOf('\0') < 0;
    }

    private String mimeType(String path) {
        String extension = MimeTypeMap.getFileExtensionFromUrl(path.toLowerCase(Locale.ROOT));
        String detected = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension);
        if (detected != null) return detected;
        if (path.endsWith(".js")) return "application/javascript";
        if (path.endsWith(".json") || path.endsWith(".webmanifest")) return "application/json";
        if (path.endsWith(".svg")) return "image/svg+xml";
        return "application/octet-stream";
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        showingOfflineFallback = false;
        if (webView != null) webView.loadUrl(resolveLaunchUrl(intent));
    }

    @Override
    protected void onDestroy() {
        if (playBilling != null) {
            playBilling.close();
            playBilling = null;
        }
        if (webView != null) {
            webView.loadUrl("about:blank");
            webView.stopLoading();
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }
}
