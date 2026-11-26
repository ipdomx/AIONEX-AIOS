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

const page = {
  'id': 'acc1',
  'provider': 'facebook',
  'display_name': 'IPDOMX Page',
  'handle': null,
  'status': 'active',
  'health_state': 'healthy',
  'last_health_at': '2026-11-26T09:00:00Z',
};

Map<String, Object?> post(String status, {String? permalink}) => {
      'id': 'post1',
      'status': status,
      'post_type': 'text',
      'caption': 'Launch day #aionex',
      'media': <Object>[],
      'scheduled_at': null,
      'timezone': 'UTC',
      'published_at': status == 'published' ? '2026-11-26T10:00:00Z' : null,
      'created_at': '2026-11-26T09:59:00Z',
      'targets': [
        {
          'id': 't1',
          'account_id': 'acc1',
          'provider': 'facebook',
          'account_name': 'IPDOMX Page',
          'status': status == 'published' ? 'published' : 'publishing',
          'attempts': 1,
          'max_attempts': 3,
          'permalink': permalink,
          'error_code': null,
        },
      ],
    };

void main() {
  testWidgets('a post is checked, created, published and followed in the calendar', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.6;
    addTearDown(tester.view.reset);
    var posts = <Object>[];
    final sent = <String, Object?>{};
    SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
    final preferences = await SharedPreferences.getInstance();
    final store = MemorySessionStore(refreshToken: 'saved');
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
        ('GET', '/auth/me') => jsonBody(200, userJson()),
        ('GET', '/social/accounts') => jsonBody(200, {'items': [page]}),
        ('GET', '/social/media') => jsonBody(200, {'uploads': <Object>[], 'studio': <Object>[]}),
        ('GET', '/social/posts') => jsonBody(200, {'items': posts}),
        ('POST', '/social/posts/validate') => () {
            sent['validate'] = body(request);
            return jsonBody(200, {
              'valid': true,
              'targets': [
                {'target_id': null, 'account_id': 'acc1', 'provider': 'facebook', 'issues': <Object>[]},
              ],
              'media': <Object>[],
            });
          }(),
        ('POST', '/social/posts') => () {
            sent['create'] = body(request);
            return jsonBody(201, post('draft'));
          }(),
        ('POST', '/social/posts/post1/publish') => () {
            sent['publish'] = true;
            posts = [post('publishing')];
            return jsonBody(202, post('publishing'));
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
    container.read(routerProvider).go('/social');
    await tester.pumpAndSettle();
    expect(find.text('IPDOMX Page'), findsOneWidget);
    expect(find.textContaining('Healthy'), findsOneWidget);

    await tester.tap(find.text('Compose'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('compose-account-acc1')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('compose-caption')), 'Launch day #aionex');
    await tester.pumpAndSettle();
    expect(find.textContaining('18/2200 characters'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('compose-publish')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('compose-publish')));
    await tester.pumpAndSettle();

    final created = sent['create']! as Map;
    expect(created['account_ids'], ['acc1']);
    expect(created['post_type'], 'text');
    expect((created['client_idempotency_key'] as String).isNotEmpty, isTrue);
    expect((sent['validate']! as Map)['caption'], 'Launch day #aionex');
    expect(sent['publish'], isTrue);
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();

    await tester.tap(find.text('Calendar'));
    await tester.pumpAndSettle();
    expect(find.text('Publishing'), findsWidgets);

    posts = [post('published', permalink: 'https://www.facebook.com/123')];
    await tester.pump(const Duration(seconds: 5));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Published'), findsOneWidget);
    expect(find.byTooltip('View live post'), findsOneWidget);
  });
}
