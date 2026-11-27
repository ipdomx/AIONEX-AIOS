import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_android/in_app_purchase_android.dart';

import '../../core/api/api_client.dart';
import '../../core/auth/session_controller.dart';
import '../../core/providers.dart';
import 'billing_page.dart';

/// The store this build sells through: Apple and Google require their own
/// purchase flow for digital subscriptions, so the app never opens a web checkout.
String? currentStore() {
  if (kIsWeb) return null;
  return switch (defaultTargetPlatform) {
    TargetPlatform.iOS => 'app_store',
    TargetPlatform.android => 'google_play',
    _ => null,
  };
}

/// One owner-mapped store product (App Store Connect / Play Console) for a plan and period.
@immutable
class StoreMapping {
  const StoreMapping({
    required this.id,
    required this.productId,
    required this.planCode,
    required this.periodCode,
    this.basePlanId,
  });

  final String id;
  final String productId;
  final String planCode;
  final String periodCode;
  final String? basePlanId;

  factory StoreMapping.fromJson(Map<String, Object?> j) => StoreMapping(
        id: (j['id'] as String?) ?? '',
        productId: (j['product_id'] as String?) ?? '',
        planCode: (j['plan_code'] as String?) ?? '',
        periodCode: (j['period_code'] as String?) ?? '',
        basePlanId: j['base_plan_id'] as String?,
      );
}

/// A mapping with the store's own localized price, ready to buy.
@immutable
class StoreOffer {
  const StoreOffer({required this.mapping, required this.details});
  final StoreMapping mapping;
  final ProductDetails details;
  String get price => details.price;
}

/// The store side, behind an interface so tests do not need a real store.
abstract interface class StoreGateway {
  Future<bool> available();
  Future<List<ProductDetails>> query(Set<String> productIds);
  Stream<List<PurchaseDetails>> get purchases;
  Future<void> buy(ProductDetails details, {required String accountId});
  Future<void> complete(PurchaseDetails purchase);
  Future<void> restore({required String accountId});
}

class InAppStoreGateway implements StoreGateway {
  InAppPurchase get _iap => InAppPurchase.instance;

  @override
  Future<bool> available() => _iap.isAvailable();

  @override
  Future<List<ProductDetails>> query(Set<String> productIds) async =>
      (await _iap.queryProductDetails(productIds)).productDetails;

  @override
  Stream<List<PurchaseDetails>> get purchases => _iap.purchaseStream;

  /// [accountId] becomes Google's obfuscatedAccountId / Apple's appAccountToken (the user's UUID).
  @override
  Future<void> buy(ProductDetails details, {required String accountId}) =>
      _iap.buyNonConsumable(purchaseParam: PurchaseParam(productDetails: details, applicationUserName: accountId));

  @override
  Future<void> complete(PurchaseDetails purchase) => _iap.completePurchase(purchase);

  @override
  Future<void> restore({required String accountId}) => _iap.restorePurchases(applicationUserName: accountId);
}

final storeGatewayProvider = Provider<StoreGateway>((ref) => InAppStoreGateway());

/// What the plans page can sell right now.
@immutable
class StoreCatalog {
  const StoreCatalog({required this.store, required this.ready, required this.offers});

  /// app_store, google_play, or null on the web build.
  final String? store;

  /// False until the owner configures server verification and maps products.
  final bool ready;
  final List<StoreOffer> offers;

  List<StoreOffer> offersFor(String planCode) => [for (final o in offers) if (o.mapping.planCode == planCode) o];
}

/// The mapping a Play product detail belongs to (several base plans can share one product id).
bool _matches(StoreMapping m, ProductDetails d) {
  if (m.productId != d.id) return false;
  if (d is GooglePlayProductDetails && m.basePlanId != null) {
    final index = d.subscriptionIndex;
    final offers = d.productDetails.subscriptionOfferDetails;
    if (index == null || offers == null || index >= offers.length) return false;
    return offers[index].basePlanId == m.basePlanId;
  }
  return true;
}

final storeCatalogProvider = FutureProvider.autoDispose<StoreCatalog>((ref) async {
  final store = currentStore();
  if (store == null) return const StoreCatalog(store: null, ready: false, offers: []);
  final api = ref.watch(apiClientProvider);
  final gateway = ref.watch(storeGatewayProvider);
  final readiness = await api.getJson('/billing/mobile-store/readiness');
  final configured = readiness[store] is Map && (readiness[store]! as Map)['configured'] == true;
  if (!configured || !await gateway.available()) return StoreCatalog(store: store, ready: false, offers: const []);
  final mappings = [
    for (final r in await api.getList('/billing/mobile-store/catalog/$store'))
      if (r is Map) StoreMapping.fromJson(r.cast<String, Object?>()),
  ].where((m) => m.id.isNotEmpty && m.productId.isNotEmpty).toList();
  if (mappings.isEmpty) return StoreCatalog(store: store, ready: false, offers: const []);
  final details = await gateway.query({for (final m in mappings) m.productId});
  final offers = <StoreOffer>[
    for (final m in mappings)
      for (final d in details)
        if (_matches(m, d)) StoreOffer(mapping: m, details: d),
  ];
  return StoreCatalog(store: store, ready: offers.isNotEmpty, offers: offers);
});

enum PurchaseStage { idle, pending, verifying, done, failed }

@immutable
class PurchaseState {
  const PurchaseState(this.stage, {this.message});
  final PurchaseStage stage;
  final String? message;
}

/// Listens to the store for the whole session (purchases can finish after a restart),
/// has the server verify each one, and only then tells the store it was delivered.
class StorePurchaseController extends Notifier<PurchaseState> {
  StreamSubscription<List<PurchaseDetails>>? _subscription;
  final Map<String, StoreMapping> _chosen = {};

  @override
  PurchaseState build() {
    final store = currentStore();
    if (store != null) {
      _subscription = ref.watch(storeGatewayProvider).purchases.listen(_onPurchases, onError: (_) {
        state = const PurchaseState(PurchaseStage.failed);
      });
      ref.onDispose(() => _subscription?.cancel());
    }
    return const PurchaseState(PurchaseStage.idle);
  }

  String? get _accountId {
    final session = ref.read(sessionProvider).value;
    return session is SignedIn ? session.user.id : null;
  }

  Future<void> buy(StoreOffer offer) async {
    final account = _accountId;
    if (account == null) return;
    _chosen[offer.mapping.productId] = offer.mapping;
    state = const PurchaseState(PurchaseStage.pending);
    try {
      await ref.read(storeGatewayProvider).buy(offer.details, accountId: account);
    } on Object {
      state = const PurchaseState(PurchaseStage.failed);
    }
  }

  Future<void> restore() async {
    final account = _accountId;
    if (account == null) return;
    state = const PurchaseState(PurchaseStage.pending);
    try {
      await ref.read(storeGatewayProvider).restore(accountId: account);
    } on Object {
      state = const PurchaseState(PurchaseStage.failed);
    }
  }

  Future<void> _onPurchases(List<PurchaseDetails> purchases) async {
    for (final purchase in purchases) {
      switch (purchase.status) {
        case PurchaseStatus.pending:
          state = const PurchaseState(PurchaseStage.pending);
        case PurchaseStatus.canceled:
          state = const PurchaseState(PurchaseStage.idle);
          if (purchase.pendingCompletePurchase) await ref.read(storeGatewayProvider).complete(purchase);
        case PurchaseStatus.error:
          state = const PurchaseState(PurchaseStage.failed);
          if (purchase.pendingCompletePurchase) await ref.read(storeGatewayProvider).complete(purchase);
        case PurchaseStatus.purchased || PurchaseStatus.restored:
          await _verify(purchase);
      }
    }
  }

  Future<void> _verify(PurchaseDetails purchase) async {
    final store = currentStore();
    if (store == null) return;
    state = const PurchaseState(PurchaseStage.verifying);
    StoreMapping? mapping = _chosen[purchase.productID];
    if (mapping == null) {
      // A purchase finished after a restart, or a restore: look the product up again.
      final catalog = await ref.read(storeCatalogProvider.future);
      mapping = catalog.offers.where((o) => o.mapping.productId == purchase.productID).firstOrNull?.mapping;
    }
    if (mapping == null) {
      state = const PurchaseState(PurchaseStage.failed);
      return;
    }
    final token = purchase.verificationData.serverVerificationData;
    try {
      await ref.read(apiClientProvider).postJson(
            '/billing/mobile-store/verify',
            body: {
              'store': store,
              'product_record_id': mapping.id,
              if (store == 'app_store') 'signed_transaction': token else 'purchase_token': token,
            },
            retry: false,
          );
    } on Object {
      // Not delivered: the store keeps the purchase open and replays it on the next start.
      state = const PurchaseState(PurchaseStage.failed);
      return;
    }
    if (purchase.pendingCompletePurchase) await ref.read(storeGatewayProvider).complete(purchase);
    _chosen.remove(purchase.productID);
    await ref.read(sessionProvider.notifier).reloadUser();
    ref.invalidate(billingSummaryProvider);
    state = const PurchaseState(PurchaseStage.done);
  }
}

final storePurchaseProvider = NotifierProvider<StorePurchaseController, PurchaseState>(StorePurchaseController.new);
