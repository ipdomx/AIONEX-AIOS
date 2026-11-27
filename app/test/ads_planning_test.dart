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

Map<String, Object?> paid(String stage) => {
      'id': 'pc1',
      'name': 'Summer sales',
      'objective': 'traffic',
      'approval_status': 'pending',
      'currency': 'USD',
      'total_budget_minor': 50000,
      'daily_budget_cap_minor': 5000,
      'delivery_stage': stage,
      'manual_review_required': false,
    };

Future<void> reveal(WidgetTester tester, Finder finder) async {
  await tester.scrollUntilVisible(finder, 200, scrollable: find.byType(Scrollable).hitTestable().first);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('planning alone opens the page; the budget is checked, simulated and sent for owner approval',
      (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.6;
    addTearDown(tester.view.reset);
    SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
    final preferences = await SharedPreferences.getInstance();
    final store = MemorySessionStore(refreshToken: 'saved');
    Object? sent;
    var history = <Map<String, Object?>>[];
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
        ('GET', '/auth/me') => jsonBody(200, userJson()),
        ('GET', '/ads/access') => jsonBody(403, {
            'detail': {'code': 'ADS_PLAN_REQUIRED'},
          }),
        ('GET', '/growth-social/paid-campaigns/readiness') => jsonBody(200, {
            'campaigns_visible': true,
            'linked_ad_accounts': [
              {
                'id': 'sa1',
                'provider': 'meta',
                'display_name': 'IPDOMX Meta',
                'currency': 'USD',
                'live_objectives': ['traffic'],
              },
            ],
          }),
        ('GET', '/growth-social/paid-campaigns') => jsonBody(200, {'items': history}),
        ('POST', '/growth-social/paid-campaigns/prepare-and-simulate') => () {
            sent = body(request);
            history = [paid('awaiting_owner')];
            return jsonBody(200, {
              'campaign': paid('awaiting_owner'),
              'budget_assessment': {
                'recommendation': 'keep_and_measure',
                'observed_cpa_minor': 850,
                'observed_roas': 2.4,
              },
            });
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

    // No ads plan: no ads tabs, but the planning form is there.
    expect(find.text('Dashboard'), findsNothing);
    expect(find.text('Create and analyze a campaign'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('plan-name')), 'Summer sales');
    await tester.enterText(find.byKey(const Key('plan-total')), '50');
    await tester.enterText(find.byKey(const Key('plan-daily')), '80');
    await reveal(tester, find.byKey(const Key('plan-submit')));
    await tester.tap(find.byKey(const Key('plan-submit')));
    await tester.pumpAndSettle();
    expect(find.text('Enter a valid total and daily budget; the daily budget cannot exceed the total.'), findsOneWidget);
    expect(sent, isNull);

    await tester.drag(find.byType(Scrollable).hitTestable().first, const Offset(0, 3000));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('plan-total')), '500');
    await tester.enterText(find.byKey(const Key('plan-daily')), '50');
    await reveal(tester, find.byKey(const Key('plan-countries')));
    await tester.enterText(find.byKey(const Key('plan-countries')), 'sa, ae');
    await reveal(tester, find.byKey(const Key('plan-submit')));
    await tester.tap(find.byKey(const Key('plan-submit')));
    await tester.pumpAndSettle();

    final input = sent! as Map;
    expect(input['social_account_id'], 'sa1');
    expect(input['total_budget_minor'], 50000);
    expect(input['daily_budget_cap_minor'], 5000);
    expect(input['target_countries'], ['SA', 'AE']);
    expect(input['placements'], ['feed']);
    expect(input['max_cpa_minor'], isNull);
    expect(input['days'], 3);

    await reveal(tester, find.byKey(const Key('plan-result')));
    expect(find.text('Recommendation: Keep the budget and measure'), findsOneWidget);
    expect(find.text('Simulated ROAS: 2.40'), findsOneWidget);
    await reveal(tester, find.byKey(const Key('plan-campaign-pc1')));
    expect(find.text('Awaiting Owner approval'), findsWidgets);
  });
}
