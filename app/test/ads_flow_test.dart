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

Map<String, Object?> access({bool allowed = true}) => {
      'allowed': allowed,
      'level': allowed ? 'subscriber' : null,
      'source': null,
      'reason': allowed ? 'ok' : 'plan',
      'plan_code': 'business',
      'entitlement': 'ads.management',
      'activation_enabled': true,
      'daily_cap_minor': 5000,
      'lifetime_cap_minor': 50000,
      'max_ad_accounts': 3,
      'max_active_campaigns': 2,
      'owner_token_fallback': false,
      'live_verified': true,
      'activation_phrase': 'ACTIVATE SPEND',
    };

const link = {
  'id': 'l1',
  'ad_account_id': 'act_1',
  'name': 'IPDOMX Ads',
  'currency': 'USD',
  'sync_state': 'ok',
  'sync_error': null,
  'last_sync_at': '2026-11-26T09:00:00Z',
  'insights_synced_through': '2026-11-25',
};

Map<String, Object?> campaign(String status) => {
      'id': 'c1',
      'link_id': 'l1',
      'name': 'Winter traffic',
      'objective': 'traffic',
      'status': status,
      'currency': 'USD',
      'daily_budget_minor': 2000,
      'lifetime_budget_minor': null,
      'spend_today': 0,
      'spend_to_date': 0,
      'pause_reason': null,
      'error_code': null,
    };

Future<FakeAdapter> start(WidgetTester tester, Map<String, Object?> sent, {bool allowed = true}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final store = MemorySessionStore(refreshToken: 'saved');
  var status = 'paused';
  final adapter = FakeAdapter((request) async {
    final path = request.uri.path.replaceFirst('/api/v1', '');
    return switch ((request.method, path)) {
      ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
      ('GET', '/auth/me') => jsonBody(200, userJson()),
      ('GET', '/ads/access') => jsonBody(200, access(allowed: allowed)),
      ('GET', '/ads/accounts') => jsonBody(200, {'items': [link]}),
      ('GET', '/ads/analytics') => jsonBody(200, {
          'link': link,
          'currency': 'USD',
          'period': {'from': '2026-11-12', 'to': '2026-11-25'},
          'previous_period': {'from': '2026-10-29', 'to': '2026-11-11'},
          'kpis': {
            'spend': {'value': 120.5, 'previous': 100, 'change_pct': 20.5},
            'clicks': {'value': 3400, 'previous': 3000, 'change_pct': 13.3},
          },
          'trend': <Object>[],
          'campaigns': {'basis': 'roas', 'top': <Object>[], 'bottom': <Object>[], 'count': 0},
          'breakdowns': <String, Object>{},
          'alerts': <Object>[],
          'has_data': true,
          'synced_through': '2026-11-25',
          'simulated': false,
          'live_verified': true,
        }),
      ('GET', '/ads/recommendations') => jsonBody(200, {'item': null}),
      ('GET', '/ads/campaigns') => jsonBody(200, {'items': [campaign(status)]}),
      ('POST', '/ads/campaigns/c1/activate') => () {
          sent['activate'] = body(request);
          status = 'active';
          return jsonBody(200, campaign('active'));
        }(),
      ('POST', '/ads/campaigns/c1/pause') => () {
          sent['pause'] = true;
          status = 'paused';
          return jsonBody(200, campaign('paused'));
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
      deviceIntegrityProvider.overrideWith((ref) async => DeviceIntegrity.unknown),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
  await tester.pumpAndSettle();
  container.read(routerProvider).go('/ads');
  await tester.pumpAndSettle();
  return adapter;
}

void main() {
  testWidgets('real numbers show, and activation needs the exact phrase and budget', (tester) async {
    final sent = <String, Object?>{};
    await start(tester, sent);
    expect(find.byKey(const Key('kpi-spend')), findsOneWidget);
    expect(find.textContaining('▲ 20.5%'), findsOneWidget);

    await tester.tap(find.text('My platform campaigns'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ads-activate-c1')));
    await tester.pumpAndSettle();
    final confirm = find.byKey(const Key('activate-confirm'));
    expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
    await tester.enterText(find.byKey(const Key('activate-phrase')), 'activate spend');
    await tester.enterText(find.byKey(const Key('activate-budget')), '20');
    await tester.pumpAndSettle();
    // Wrong case: still locked.
    expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
    await tester.enterText(find.byKey(const Key('activate-phrase')), 'ACTIVATE SPEND');
    await tester.pumpAndSettle();
    await tester.tap(confirm);
    await tester.pumpAndSettle();
    expect(sent['activate'], {'confirmation': 'ACTIVATE SPEND', 'confirmed_budget_minor': 2000});

    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ads-pause-c1')));
    await tester.pumpAndSettle();
    expect(sent['pause'], isTrue);
  });

  testWidgets('a plan without ads sees the upgrade notice', (tester) async {
    final adapter = await start(tester, {}, allowed: false);
    expect(find.text('Meta Ads management is not in your plan'), findsOneWidget);
    expect(adapter.paths.where((p) => p.contains('/ads/campaigns')), isEmpty);
  });
}
