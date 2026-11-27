import 'dart:convert';

import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:aionex/src/core/router/app_router.dart';
import 'package:aionex/src/core/security/device_security.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

Object? body(RequestOptions request) => request.data is String ? jsonDecode(request.data as String) : request.data;

Future<ProviderContainer> pumpApp(WidgetTester tester, Handler handler) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final store = MemorySessionStore(refreshToken: 'saved');
  final container = ProviderContainer(
    retry: retryOnlyNetworkErrors,
    overrides: [
      sharedPreferencesProvider.overrideWithValue(preferences),
      sessionStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(fakeClient(FakeAdapter(handler), store)),
      deviceIntegrityProvider.overrideWith((ref) async => DeviceIntegrity.unknown),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
  await tester.pumpAndSettle();
  return container;
}

Future<void> tapVisible(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('settings: channels and severity, Telegram code, add and remove an address', (tester) async {
    final reader = userJson(plan: 'Pro', permissions: ['notifications:read', 'notifications:write']);
    Object? savedPreference;
    Object? addedEndpoint;
    final removed = <String>[];
    final endpoints = <Map<String, Object?>>[
      {
        'id': 'e1',
        'channel': 'push',
        'label': 'This phone',
        'masked_address': 'fcm…a1',
        'verified': true,
        'status': 'active',
      },
    ];
    final clipboard = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') clipboard.add((call.arguments as Map)['text'] as String);
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));

    final container = await pumpApp(tester, (request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, {...grantJson(), 'user': reader}),
        ('GET', '/auth/me') => jsonBody(200, reader),
        ('GET', '/notifications') => jsonBody(200, {'items': <Object>[]}),
        ('GET', '/communications/channels') => jsonBody(200, [
            {'id': 'in_app', 'name': 'In-app', 'ready': true, 'owner_only': false},
            {'id': 'email', 'name': 'Email', 'ready': true, 'owner_only': false},
            {'id': 'telegram', 'name': 'Telegram', 'ready': false, 'owner_only': false},
            {'id': 'ops', 'name': 'Owner ops', 'ready': true, 'owner_only': true},
          ]),
        ('GET', '/communications/endpoints') => jsonBody(200, endpoints),
        ('GET', '/communications/preferences') => jsonBody(200, [
            {
              'id': 'p1',
              'category': '*',
              'enabled': true,
              'channels': ['in_app'],
              'minimum_severity': 'info',
              'quiet_hours_start': null,
              'quiet_hours_end': null,
              'timezone': 'Asia/Riyadh',
              'digest_mode': 'immediate',
            },
          ]),
        ('PUT', '/communications/preferences') => () {
            savedPreference = body(request);
            return jsonBody(200, {...(savedPreference! as Map).cast<String, Object?>(), 'id': 'p1'});
          }(),
        ('GET', '/telegram/status') => jsonBody(200, {
            'configured': true,
            'linked': false,
            'link_current': true,
            'bot_username': 'aionex_bot',
          }),
        ('POST', '/telegram/link-challenge') => jsonBody(200, {
            'code': 'LINK-1234',
            'expires_in_seconds': 300,
            'bot_username': 'aionex_bot',
            'deep_link': 'https://t.me/aionex_bot?start=LINK-1234',
          }),
        ('POST', '/communications/endpoints') => () {
            addedEndpoint = body(request);
            endpoints.add({
              'id': 'e2',
              'channel': 'email',
              'label': 'Work',
              'masked_address': 'w***@example.com',
              'verified': true,
              'status': 'active',
            });
            return jsonBody(201, endpoints.last);
          }(),
        ('DELETE', '/communications/endpoints/e2') => () {
            removed.add('e2');
            endpoints.removeWhere((e) => e['id'] == 'e2');
            return jsonBody(200, {'id': 'e2', 'channel': 'email', 'label': 'Work', 'verified': true});
          }(),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });

    container.read(routerProvider).go('/notifications');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('notification-settings')));
    await tester.pumpAndSettle();

    // Owner-only channels are hidden; in-app cannot be switched off.
    expect(find.byKey(const Key('pref-channel-ops')), findsNothing);
    expect(tester.widget<CheckboxListTile>(find.byKey(const Key('pref-channel-in_app'))).onChanged, isNull);
    await tester.tap(find.byKey(const Key('pref-channel-email')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('pref-severity')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Critical').last);
    await tester.pumpAndSettle();
    await tapVisible(tester, find.byKey(const Key('pref-save')));
    final saved = savedPreference! as Map;
    expect(saved['channels'], ['in_app', 'email']);
    expect(saved['minimum_severity'], 'critical');
    expect(saved['timezone'], 'Asia/Riyadh');

    await tapVisible(tester, find.byKey(const Key('telegram-create')));
    expect(find.text('LINK-1234'), findsOneWidget);
    expect(find.byKey(const Key('telegram-open')), findsOneWidget);
    await tapVisible(tester, find.byKey(const Key('telegram-copy')));
    expect(clipboard, ['LINK-1234']);

    await tester.ensureVisible(find.byKey(const Key('endpoint-address')));
    await tester.enterText(find.byKey(const Key('endpoint-address')), 'work@example.com');
    await tester.enterText(find.byKey(const Key('endpoint-label')), 'Work');
    await tapVisible(tester, find.byKey(const Key('endpoint-add')));
    expect(addedEndpoint, {'channel': 'email', 'address': 'work@example.com', 'label': 'Work'});
    expect(find.byKey(const Key('endpoint-e2')), findsOneWidget);

    await tapVisible(tester, find.byKey(const Key('endpoint-remove-e2')));
    expect(removed, ['e2']);
    expect(find.byKey(const Key('endpoint-e2')), findsNothing);
    expect(find.byKey(const Key('endpoint-e1')), findsOneWidget);
  });
}
