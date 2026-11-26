import 'dart:convert';

import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:aionex/src/core/router/app_router.dart';
import 'package:aionex/src/core/security/device_security.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

Object? body(RequestOptions request) => request.data is String ? jsonDecode(request.data as String) : request.data;

Map<String, Object?> summary({bool cancelling = false}) => {
      'account': {
        'id': 'b1',
        'status': 'active',
        'licensed_seats': 1,
        'plan': 'professional',
        'plan_name': 'Professional',
        'limits': {'projects': 20},
        'entitlements': <String>[],
        'usage': {'projects': 3},
        'current_period_end': '2026-12-26T00:00:00Z',
      },
      'subscription': {
        'id': 's1',
        'provider': 'stripe',
        'source': 'web',
        'provider_label': 'Stripe',
        'management_url': null,
        'status': 'active',
        'cancel_at_period_end': cancelling,
        'current_period_start': '2026-11-26T00:00:00Z',
        'current_period_end': '2026-12-26T00:00:00Z',
        'canceled_at': null,
      },
      'invoices': [
        {'id': 'i1', 'number': 'INV-1', 'provider': 'stripe', 'status': 'paid', 'currency': 'USD', 'total_minor': 9300, 'created_at': '2026-11-26T00:00:00Z'},
      ],
      'transactions': <Object>[],
      'wallet': {'id': 'w1', 'currency': 'USD', 'balance_minor': 0, 'status': 'active'},
      'catalog_version': 1,
    };

Future<void> start(WidgetTester tester, Map<String, Object?> sent, {bool compromised = false}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final store = MemorySessionStore(refreshToken: 'saved');
  var cancelling = false;
  final adapter = FakeAdapter((request) async {
    final path = request.uri.path.replaceFirst('/api/v1', '');
    return switch ((request.method, path)) {
      ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
      ('GET', '/auth/me') => jsonBody(200, userJson()),
      ('GET', '/billing') => jsonBody(200, summary(cancelling: cancelling)),
      ('GET', '/billing/payment-methods') => jsonBody(200, [
          {'id': 'pm1', 'provider': 'stripe', 'type': 'card', 'brand': 'visa', 'last4': '4242', 'expiry_month': 4, 'expiry_year': 2030, 'is_default': true},
        ]),
      ('POST', '/billing/subscription/cancel') => () {
          sent['cancel'] = body(request);
          cancelling = true;
          return jsonBody(200, summary(cancelling: true)['subscription']!);
        }(),
      ('POST', '/billing/subscription/resume') => () {
          sent['resumeKey'] = request.headers['Idempotency-Key'];
          cancelling = false;
          return jsonBody(200, summary()['subscription']!);
        }(),
      _ => jsonBody(404, {'detail': 'not found'}),
    };
  });
  final container = ProviderContainer(
    retry: retryOnlyNetworkErrors,
    overrides: [
      sharedPreferencesProvider.overrideWithValue(preferences),
      sessionStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(fakeClient(adapter, store)),
      deviceIntegrityProvider.overrideWith(
        (ref) async => compromised ? const DeviceIntegrity(compromised: true, emulator: false, debugBuild: false, signals: ['su']) : DeviceIntegrity.unknown,
      ),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
  await tester.pumpAndSettle();
  container.read(routerProvider).go('/billing');
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('plan, invoices and cards show; cancellation is scheduled and undone', (tester) async {
    final sent = <String, Object?>{};
    await start(tester, sent);
    expect(find.text('Professional'), findsOneWidget);
    expect(find.text('visa •••• 4242'), findsOneWidget);
    expect(find.text('Invoice INV-1'), findsOneWidget);

    await tester.tap(find.byKey(const Key('billing-cancel')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel at period end').last);
    await tester.pumpAndSettle();
    expect(sent['cancel'], {'immediately': false});
    expect(find.text('Cancellation scheduled'), findsOneWidget);

    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('billing-resume')));
    await tester.pumpAndSettle();
    expect((sent['resumeKey'] as String).isNotEmpty, isTrue);
  });

  testWidgets('a compromised device cannot change how it pays', (tester) async {
    await start(tester, {}, compromised: true);
    expect(find.byKey(const Key('billing-compromised')), findsOneWidget);
    expect(tester.widget<TextButton>(find.byKey(const Key('billing-cancel'))).onPressed, isNull);
  });
}
