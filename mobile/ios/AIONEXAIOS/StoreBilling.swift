import Foundation
import StoreKit

struct StoreProductRecord: Decodable, Identifiable {
    let id: String
    let productId: String
    let planCode: String
    let periodCode: String
    let active: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case productId = "product_id"
        case planCode = "plan_code"
        case periodCode = "period_code"
        case active
    }
}

@MainActor
final class StoreBilling: ObservableObject {
    static let shared = StoreBilling()
    @Published private(set) var products: [Product] = []
    @Published private(set) var isLoading = false
    @Published private(set) var lastError: String?

    private var records: [String: StoreProductRecord] = [:]
    private var listener: Task<Void, Never>?
    private let api = StoreBillingAPI()
    private var accessToken: String?

    private init() {
        listener = listenForTransactions()
    }

    deinit { listener?.cancel() }

    func setAccessToken(_ token: String?) {
        accessToken = token
    }

    func loadProducts() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let catalogue = try await api.catalogue(accessToken: accessToken)
            records = Dictionary(uniqueKeysWithValues: catalogue.filter(\.active).map { ($0.productId, $0) })
            products = try await Product.products(for: records.keys).sorted { $0.displayPrice < $1.displayPrice }
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func purchase(_ product: Product) async throws {
        guard let record = records[product.id] else { throw StoreBillingError.unmappedProduct }
        let result = try await product.purchase()
        switch result {
        case .success(let verification):
            let transaction = try verified(verification)
            try await api.submit(recordId: record.id, signedTransaction: verification.jwsRepresentation, accessToken: accessToken)
            await transaction.finish()
        case .pending:
            throw StoreBillingError.pending
        case .userCancelled:
            return
        @unknown default:
            throw StoreBillingError.unknownResult
        }
    }

    func restore() async throws {
        try await AppStore.sync()
        for await result in Transaction.currentEntitlements {
            guard case .verified(let transaction) = result,
                  let record = records[transaction.productID] else { continue }
            try await api.submit(recordId: record.id, signedTransaction: result.jwsRepresentation, accessToken: accessToken)
        }
    }

    func syncCurrentEntitlements() async {
        for await result in Transaction.currentEntitlements {
            guard case .verified(let transaction) = result,
                  let record = records[transaction.productID] else { continue }
            try? await api.submit(recordId: record.id, signedTransaction: result.jwsRepresentation, accessToken: accessToken)
        }
    }

    private func listenForTransactions() -> Task<Void, Never> {
        Task { [weak self] in
            for await result in Transaction.updates {
                guard let self, case .verified(let transaction) = result else { continue }
                if let record = self.records[transaction.productID] {
                    do {
                        try await self.api.submit(recordId: record.id, signedTransaction: result.jwsRepresentation)
                        await transaction.finish()
                    } catch { self.lastError = error.localizedDescription }
                }
            }
        }
    }

    private func verified<T>(_ result: VerificationResult<T>) throws -> T {
        switch result {
        case .verified(let value): return value
        case .unverified: throw StoreBillingError.failedVerification
        }
    }
}

enum StoreBillingError: LocalizedError {
    case unmappedProduct, pending, unknownResult, failedVerification, missingSession
    var errorDescription: String? {
        switch self {
        case .unmappedProduct: return "Subscription product is not mapped by AIONEX."
        case .pending: return "Purchase is pending approval."
        case .unknownResult: return "Unknown App Store purchase result."
        case .failedVerification: return "App Store transaction verification failed."
        case .missingSession: return "Sign in to AIONEX before purchasing."
        }
    }
}

private struct StoreBillingAPI {
    private let base = URL(string: "https://ai.vip-e.net/api/v1/billing/mobile-store")!

    func catalogue(accessToken: String?) async throws -> [StoreProductRecord] {
        let data = try await request(path: "catalog/app_store", method: "GET", body: nil, accessToken: accessToken)
        return try JSONDecoder().decode([StoreProductRecord].self, from: data)
    }

    func submit(recordId: String, signedTransaction: String, accessToken: String?) async throws {
        let body = try JSONSerialization.data(withJSONObject: [
            "store": "app_store",
            "product_record_id": recordId,
            "signed_transaction": signedTransaction
        ])
        _ = try await request(path: "verify", method: "POST", body: body, accessToken: accessToken)
    }

    private func request(path: String, method: String, body: Data?, accessToken: String?) async throws -> Data {
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        guard let accessToken, !accessToken.isEmpty else { throw StoreBillingError.missingSession }
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.httpShouldHandleCookies = true
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw URLError(.userAuthenticationRequired)
        }
        return data
    }
}
