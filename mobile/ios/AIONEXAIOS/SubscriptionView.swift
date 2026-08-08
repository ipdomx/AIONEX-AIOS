import StoreKit
import SwiftUI
import UIKit

private enum StoreCopy {
    static var language: String { Locale.current.language.languageCode?.identifier ?? "en" }
    static let values: [String: [String: String]] = [
        "en": ["title":"AIONEX Subscription","loading":"Loading subscriptions…","subscribe":"Subscribe","restore":"Restore Purchases","manage":"Manage in App Store","none":"No subscriptions are currently available."],
        "ar": ["title":"اشتراك AIONEX","loading":"جارٍ تحميل الاشتراكات…","subscribe":"اشترك","restore":"استعادة المشتريات","manage":"إدارة الاشتراك في App Store","none":"لا توجد اشتراكات متاحة حاليًا."],
        "fr": ["title":"Abonnement AIONEX","loading":"Chargement des abonnements…","subscribe":"S’abonner","restore":"Restaurer les achats","manage":"Gérer dans l’App Store","none":"Aucun abonnement disponible."],
        "de": ["title":"AIONEX-Abonnement","loading":"Abonnements werden geladen…","subscribe":"Abonnieren","restore":"Käufe wiederherstellen","manage":"Im App Store verwalten","none":"Derzeit sind keine Abonnements verfügbar."],
        "es": ["title":"Suscripción AIONEX","loading":"Cargando suscripciones…","subscribe":"Suscribirse","restore":"Restaurar compras","manage":"Gestionar en App Store","none":"No hay suscripciones disponibles."],
        "tr": ["title":"AIONEX Aboneliği","loading":"Abonelikler yükleniyor…","subscribe":"Abone ol","restore":"Satın alımları geri yükle","manage":"App Store’da yönet","none":"Şu anda kullanılabilir abonelik yok."]
    ]
    static func text(_ key: String) -> String { values[language]?[key] ?? values["en"]![key]! }
}

struct SubscriptionView: View {
    @StateObject private var billing = StoreBilling.shared

    var body: some View {
        NavigationStack {
            List {
                if billing.isLoading { ProgressView(StoreCopy.text("loading")) }
                if !billing.isLoading && billing.products.isEmpty {
                    Text(StoreCopy.text("none")).foregroundStyle(.secondary)
                }
                ForEach(billing.products, id: \.id) { product in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(product.displayName).font(.headline)
                        Text(product.description).font(.subheadline).foregroundStyle(.secondary)
                        Button("\(StoreCopy.text("subscribe")) — \(product.displayPrice)") {
                            Task { try? await billing.purchase(product) }
                        }.buttonStyle(.borderedProminent)
                    }.padding(.vertical, 6)
                }
                Section {
                    Button(StoreCopy.text("restore")) { Task { try? await billing.restore() } }
                    Button(StoreCopy.text("manage")) {
                        if let url = URL(string: "https://apps.apple.com/account/subscriptions") {
                            UIApplication.shared.open(url)
                        }
                    }
                }
                if let error = billing.lastError { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle(StoreCopy.text("title"))
            .task { await billing.loadProducts(); await billing.syncCurrentEntitlements() }
        }
    }
}
