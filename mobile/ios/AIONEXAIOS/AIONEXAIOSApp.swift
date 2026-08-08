import SwiftUI

@main
struct AIONEXAIOSApp: App {
    @State private var showSubscription = false

    var body: some Scene {
        WindowGroup {
            PortalView()
                .onReceive(NotificationCenter.default.publisher(for: .aionexShowNativeSubscription)) { _ in
                    showSubscription = true
                }
                .sheet(isPresented: $showSubscription) { SubscriptionView() }
                .preferredColorScheme(.dark)
        }
    }
}
