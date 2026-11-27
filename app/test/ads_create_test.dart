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

const access = {
  'allowed': true,
  'activation_enabled': true,
  'daily_cap_minor': 5000,
  'lifetime_cap_minor': 50000,
  'live_verified': true,
  'activation_phrase': 'ACTIVATE SPEND',
};

Map<String, Object?> link({int? cpa}) => {
      'id': 'l1',
      'ad_account_id': 'act_1',
      'name': 'IPDOMX Ads',
      'currency': 'USD',
      'sync_state': 'ok',
      'last_sync_at': '2026-11-26T09:00:00Z',
      'cpa_target_minor': cpa,
    };

Map<String, Object?> campaign(String status) => {
      'id': 'c1',
      'name': 'Winter traffic',
      'objective': 'traffic',
      'status': status,
      'currency': 'USD',
      'daily_budget_minor': 2000,
      'spend_today': 0,
      'spend_to_date': 0,
    };

Future<ProviderContainer> start(WidgetTester tester, Map<String, Object?> sent) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final store = MemorySessionStore(refreshToken: 'saved');
  var campaigns = <Map<String, Object?>>[campaign('failed')];
  var links = <Map<String, Object?>>[link()];
  final adapter = FakeAdapter((request) async {
    final path = request.uri.path.replaceFirst('/api/v1', '');
    return switch ((request.method, path)) {
      ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
      ('GET', '/auth/me') => jsonBody(200, userJson()),
      ('GET', '/ads/access') => jsonBody(200, access),
      ('GET', '/ads/accounts') => jsonBody(200, {'items': links}),
      ('GET', '/ads/analytics') => jsonBody(200, {'currency': 'USD', 'has_data': false, 'kpis': <String, Object>{}}),
      ('GET', '/ads/recommendations') => jsonBody(200, {'item': null}),
      ('GET', '/ads/campaigns') => jsonBody(200, {'items': campaigns}),
      ('GET', '/social/accounts') => jsonBody(200, {
          'items': [
            {'id': 'pg1', 'provider': 'facebook', 'display_name': 'IPDOMX Page', 'status': 'active'},
          ],
        }),
      ('GET', '/social/media') => jsonBody(200, {'uploads': <Object>[], 'studio': <Object>[]}),
      ('GET', '/social/posts') => jsonBody(200, {
          'items': [
            {
              'id': 'p1',
              'status': 'published',
              'targets': [
                {
                  'id': 't1',
                  'account_name': 'IPDOMX Page',
                  'provider': 'facebook',
                  'status': 'published',
                  'remote_post_id': '123_456',
                  'published_at': '2026-11-20T10:00:00Z',
                },
                {'id': 't2', 'account_name': 'IPDOMX Page', 'provider': 'facebook', 'status': 'failed'},
              ],
            },
          ],
        }),
      ('POST', '/ads/campaigns') => () {
          sent['create'] = body(request);
          campaigns = [campaign('paused'), ...campaigns];
          return jsonBody(201, campaign('paused'));
        }(),
      ('POST', '/ads/campaigns/c1/provision') => () {
          sent['provision'] = true;
          return jsonBody(200, campaign('paused'));
        }(),
      ('PATCH', '/ads/accounts/l1') => () {
          sent['target'] = body(request);
          links = [link(cpa: 1250)];
          return jsonBody(200, links.first);
        }(),
      ('DELETE', '/ads/accounts/l1') => () {
          sent['unlink'] = true;
          links = [];
          return jsonBody(200, link());
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
  return container;
}

Future<void> reveal(WidgetTester tester, Finder finder) async {
  await tester.scrollUntilVisible(finder, 200, scrollable: find.byType(Scrollable).hitTestable().first);
  await tester.pumpAndSettle();
}

Future<void> tapVisible(WidgetTester tester, Finder finder) async {
  if (finder.evaluate().isEmpty) await reveal(tester, finder);
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('a campaign is created in the app from a published post, and a failed one can be retried',
      (tester) async {
    final sent = <String, Object?>{};
    final container = await start(tester, sent);
    container.read(routerProvider).go('/ads');
    await tester.pumpAndSettle();
    await tester.tap(find.text('My platform campaigns'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('ads-retry-c1')));
    await tester.pumpAndSettle();
    expect(sent['provision'], isTrue);

    await tester.tap(find.byKey(const Key('ads-create')));
    await tester.pumpAndSettle();
    expect(find.text('Create a campaign on Meta'), findsOneWidget);

    // Missing fields are caught before anything is sent.
    await tapVisible(tester, find.byKey(const Key('create-submit')));
    expect(find.byKey(const Key('create-error')), findsOneWidget);
    expect(sent.containsKey('create'), isFalse);
    await tester.drag(find.byType(Scrollable).hitTestable().first, const Offset(0, 3000));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('create-name')), 'Winter traffic');
    await tester.enterText(find.byKey(const Key('create-budget')), '20');
    await reveal(tester, find.byKey(const Key('create-countries')));
    await tester.enterText(find.byKey(const Key('create-countries')), 'sa, ae, x1');
    await tapVisible(tester, find.byKey(const Key('create-post')));
    await tester.tap(find.textContaining('IPDOMX Page · facebook').last);
    await tester.pumpAndSettle();
    await tapVisible(tester, find.byKey(const Key('create-submit')));

    final input = sent['create']! as Map;
    expect(input['link_id'], 'l1');
    expect(input['name'], 'Winter traffic');
    expect(input['daily_budget_minor'], 2000);
    expect(input['lifetime_budget_minor'], isNull);
    expect((input['targeting'] as Map)['countries'], ['SA', 'AE']);
    expect((input['targeting'] as Map)['publisher_platforms'], ['facebook', 'instagram']);
    expect(input['creative'], {'source': 'post', 'post_target_id': 't1'});
    expect((input['client_idempotency_key'] as String).length, 24);
    // Back on the list.
    expect(find.text('Create a campaign on Meta'), findsNothing);
  });

  testWidgets('target CPA is saved in minor units, and unlinking asks first', (tester) async {
    final sent = <String, Object?>{};
    final container = await start(tester, sent);
    container.read(routerProvider).go('/ads');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ad accounts'));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('ads-cpa-l1')), '12.5');
    await tapVisible(tester, find.byKey(const Key('ads-cpa-save-l1')));
    expect(sent['target'], {'cpa_target_minor': 1250});

    await tapVisible(tester, find.byKey(const Key('ads-unlink-l1')));
    expect(sent.containsKey('unlink'), isFalse);
    await tester.tap(find.byKey(const Key('unlink-confirm')));
    await tester.pumpAndSettle();
    expect(sent['unlink'], isTrue);
    expect(find.byKey(const Key('ads-link-l1')), findsNothing);
  });
}
