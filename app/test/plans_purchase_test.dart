import 'dart:async';
import 'dart:convert';

import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:aionex/src/core/router/app_router.dart';
import 'package:aionex/src/core/security/device_security.dart';
import 'package:aionex/src/features/billing/store_purchases.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

Object? body(RequestOptions request) => request.data is String ? jsonDecode(request.data as String) : request.data;

class FakeStore implements StoreGateway {
  final controller = StreamController<List<PurchaseDetails>>.broadcast();
  final bought = <String>[];
  final completed = <String>[];
  String? accountUsed;

  @override
  Future<bool> available() async => true;

  @override
  Future<List<ProductDetails>> query(Set<String> productIds) async => [
        if (productIds.contains('aionex.business.monthly'))
          ProductDetails(
            id: 'aionex.business.monthly',
            title: 'Business',
            description: 'Business monthly',
            price: 'SAR 1,749.99',
            rawPrice: 1749.99,
            currencyCode: 'SAR',
          ),
      ];

  @override
  Stream<List<PurchaseDetails>> get purchases => controller.stream;

  @override
  Future<void> buy(ProductDetails details, {required String accountId}) async {
    bought.add(details.id);
    accountUsed = accountId;
    controller.add([
      PurchaseDetails(
        productID: details.id,
        verificationData: PurchaseVerificationData(
          localVerificationData: '{}',
          serverVerificationData: 'play-token-1',
          source: 'google_play',
        ),
        transactionDate: '1764200000000',
        status: PurchaseStatus.purchased,
      )..pendingCompletePurchase = true,
    ]);
  }

  @override
  Future<void> complete(PurchaseDetails purchase) async => completed.add(purchase.productID);

  @override
  Future<void> restore({required String accountId}) async {}
}

Map<String, Object?> catalog() => {
      'enabled': true,
      'plans': [
        {
          'code': 'free',
          'enabled': true,
          'order': 10,
          'name': {'en': 'Free', 'ar': 'مجاني'},
          'description': {'en': 'Try AIONEX AIOS.'},
          'features': [
            {'en': '3 projects'},
          ],
        },
        {
          'code': 'business',
          'enabled': true,
          'featured': true,
          'order': 40,
          'name': {'en': 'Business'},
          'features': [
            {'en': '3D generation'},
          ],
        },
      ],
    };

Future<ProviderContainer> start(
  WidgetTester tester,
  Handler handler, {
  required StoreGateway store,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final session = MemorySessionStore(refreshToken: 'saved');
  final container = ProviderContainer(
    retry: retryOnlyNetworkErrors,
    overrides: [
      sharedPreferencesProvider.overrideWithValue(preferences),
      sessionStoreProvider.overrideWithValue(session),
      apiClientProvider.overrideWithValue(fakeClient(FakeAdapter(handler), session)),
      deviceIntegrityProvider.overrideWith((ref) async => DeviceIntegrity.unknown),
      storeGatewayProvider.overrideWithValue(store),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
  await tester.pumpAndSettle();
  container.read(routerProvider).go('/billing/plans');
  await tester.pumpAndSettle();
  return container;
}

Map<String, Object?> summary(String plan) => {
      'account': {'status': 'active', 'plan': plan, 'plan_name': plan},
      'invoices': <Object>[],
      'wallet': {'balance_minor': 0, 'currency': 'USD'},
    };

void main() {
  testWidgets('plans come from the catalog; buying goes through the store and the server verifies it',
      (tester) async {
    final store = FakeStore();
    Object? verified;
    var plan = 'free';
    await start(
      tester,
      (request) async {
        final path = request.uri.path.replaceFirst('/api/v1', '');
        return switch ((request.method, path)) {
          ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
          ('GET', '/auth/me') => jsonBody(200, userJson()),
          ('GET', '/billing/catalog/public') => jsonBody(200, catalog()),
          ('GET', '/billing') => jsonBody(200, summary(plan)),
          ('GET', '/billing/mobile-store/readiness') => jsonBody(200, {
              'app_store': {'configured': false},
              'google_play': {'configured': true},
            }),
          ('GET', '/billing/mobile-store/catalog/google_play') => jsonBody(200, [
              {
                'id': 'map-1',
                'store': 'google_play',
                'product_id': 'aionex.business.monthly',
                'plan_code': 'business',
                'period_code': 'monthly',
                'active': true,
              },
            ]),
          ('POST', '/billing/mobile-store/verify') => () {
              verified = body(request);
              plan = 'business';
              return jsonBody(200, {'status': 'active'});
            }(),
          _ => jsonBody(404, {'detail': 'not found'}),
        };
      },
      store: store,
    );

    expect(find.byKey(const Key('plan-current-free')), findsOneWidget);
    expect(find.text('3D generation'), findsOneWidget);
    // The price shown is the store's own, not a web price.
    final buy = find.byKey(const Key('buy-map-1'));
    expect(find.descendant(of: buy, matching: find.textContaining('SAR 1,749.99')), findsOneWidget);
    expect(find.byKey(const Key('plans-restore')), findsOneWidget);

    await tester.tap(buy);
    await tester.pumpAndSettle();

    expect(store.bought, ['aionex.business.monthly']);
    expect(store.accountUsed, 'u1');
    expect(verified, {'store': 'google_play', 'product_record_id': 'map-1', 'purchase_token': 'play-token-1'});
    // Delivered only after the server accepted it.
    expect(store.completed, ['aionex.business.monthly']);
    expect(find.text('Your plan is active.'), findsOneWidget);
    expect(find.byKey(const Key('plan-current-business')), findsOneWidget);
  });

  testWidgets('a rejected receipt is not marked delivered, so the store replays it', (tester) async {
    final store = FakeStore();
    await start(
      tester,
      (request) async {
        final path = request.uri.path.replaceFirst('/api/v1', '');
        return switch ((request.method, path)) {
          ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
          ('GET', '/auth/me') => jsonBody(200, userJson()),
          ('GET', '/billing/catalog/public') => jsonBody(200, catalog()),
          ('GET', '/billing') => jsonBody(200, summary('free')),
          ('GET', '/billing/mobile-store/readiness') => jsonBody(200, {
              'google_play': {'configured': true},
            }),
          ('GET', '/billing/mobile-store/catalog/google_play') => jsonBody(200, [
              {'id': 'map-1', 'product_id': 'aionex.business.monthly', 'plan_code': 'business', 'period_code': 'monthly'},
            ]),
          ('POST', '/billing/mobile-store/verify') => jsonBody(409, {'detail': 'Purchase belongs to another account'}),
          _ => jsonBody(404, {'detail': 'not found'}),
        };
      },
      store: store,
    );
    await tester.tap(find.byKey(const Key('buy-map-1')));
    await tester.pumpAndSettle();
    expect(store.completed, isEmpty);
    expect(find.textContaining('The purchase was not completed'), findsOneWidget);
  });

  testWidgets('before the owner configures the store, plans show with no buy button', (tester) async {
    await start(
      tester,
      (request) async {
        final path = request.uri.path.replaceFirst('/api/v1', '');
        return switch ((request.method, path)) {
          ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
          ('GET', '/auth/me') => jsonBody(200, userJson()),
          ('GET', '/billing/catalog/public') => jsonBody(200, catalog()),
          ('GET', '/billing') => jsonBody(200, summary('free')),
          ('GET', '/billing/mobile-store/readiness') => jsonBody(200, {
              'google_play': {'configured': false},
            }),
          _ => jsonBody(404, {'detail': 'not found'}),
        };
      },
      store: FakeStore(),
    );
    expect(find.byKey(const Key('plans-store-unavailable')), findsOneWidget);
    expect(find.text('Subscribing in the app will be available soon.'), findsOneWidget);
    expect(find.byKey(const Key('buy-map-1')), findsNothing);
    expect(find.byKey(const Key('plans-restore')), findsNothing);
  });
}
