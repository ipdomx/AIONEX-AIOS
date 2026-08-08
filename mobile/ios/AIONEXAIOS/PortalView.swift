import SwiftUI
import UIKit
import WebKit

struct PortalView: UIViewRepresentable {
    private static let portalHost = "ai.vip-e.net"
    private static let portalURL = URL(string: "https://ai.vip-e.net/ar/")!

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .automatic
        webView.isOpaque = false
        webView.backgroundColor = UIColor(red: 3 / 255, green: 5 / 255, blue: 10 / 255, alpha: 1)
        webView.load(URLRequest(url: Self.portalURL, cachePolicy: .useProtocolCachePolicy, timeoutInterval: 30))
        context.coordinator.webView = webView
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        private static let nativeBillingPaths = ["/billing", "/pricing"]
        weak var webView: WKWebView?
        private var showingOfflineFallback = false

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }
            if url.isFileURL {
                decisionHandler(.allow)
                return
            }
            if url.scheme == "https" && url.host == PortalView.portalHost {
                if Self.nativeBillingPaths.contains(where: { url.path.contains($0) }) {
                    NotificationCenter.default.post(name: .aionexShowNativeSubscription, object: nil)
                    decisionHandler(.cancel)
                    return
                }
                decisionHandler(.allow)
                return
            }
            if url.scheme == "https" {
                UIApplication.shared.open(url)
            }
            decisionHandler(.cancel)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            if webView.url?.host == PortalView.portalHost {
                showingOfflineFallback = false
            }
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            showOffline(in: webView)
        }

        func webView(
            _ webView: WKWebView,
            didFail navigation: WKNavigation!,
            withError error: Error
        ) {
            showOffline(in: webView)
        }

        func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            if let url = navigationAction.request.url, url.scheme == "https" {
                UIApplication.shared.open(url)
            }
            return nil
        }

        private func showOffline(in webView: WKWebView) {
            guard !showingOfflineFallback else { return }
            showingOfflineFallback = true
            guard let offlineURL = Bundle.main.url(
                forResource: "offline",
                withExtension: "html",
                subdirectory: "Web"
            ) else { return }
            webView.loadFileURL(offlineURL, allowingReadAccessTo: offlineURL.deletingLastPathComponent())
        }
    }
}

extension Notification.Name {
    static let aionexShowNativeSubscription = Notification.Name("aionexShowNativeSubscription")
}
