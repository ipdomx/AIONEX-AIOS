import StoreKit
import SwiftUI

struct SubscriptionView: View {
    @StateObject private var billing = StoreBilling.shared

    var body: some View {
        NavigationStack {
            List {
                if billing.isLoading { ProgressView("Loading subscriptions…") }
                ForEach(billing.products, id: \.id) { product in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(product.displayName).font(.headline)
                        Text(product.description).font(.subheadline).foregroundStyle(.secondary)
                        Button("Subscribe — \(product.displayPrice)") {
                            Task { try? await billing.purchase(product) }
                        }.buttonStyle(.borderedProminent)
                    }.padding(.vertical, 6)
                }
                Section {
                    Button("Restore Purchases") { Task { try? await billing.restore() } }
                }
                if let error = billing.lastError { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("AIONEX Subscription")
            .task { await billing.loadProducts(); await billing.syncCurrentEntitlements() }
        }
    }
}
