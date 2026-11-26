import 'dart:convert';

import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/firebase/firebase_setup.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:aionex/src/core/router/app_router.dart';
import 'package:aionex/src/core/security/device_security.dart';
import 'package:aionex/src/features/auth/register_page.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

class FakePhoneVerifier implements PhoneVerifier {
  final sent = <String>[];
  final codes = <String>[];

  @override
  Future<String?> sendCode(String phoneNumber) async {
    sent.add(phoneNumber);
    return null;
  }

  @override
  Future<String> confirmCode(String code) async {
    codes.add(code);
    if (code != '123456') throw StateError('wrong code');
    return 'f' * 200;
  }
}

Object? body(RequestOptions request) => request.data is String ? jsonDecode(request.data as String) : request.data;

Future<ProviderContainer> pumpApp(
  WidgetTester tester,
  Handler handler, {
  SessionStore? store,
  PhoneVerifier? verifier,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final sessionStore = store ?? MemorySessionStore();
  final container = ProviderContainer(
    retry: retryOnlyNetworkErrors,
    overrides: [
      sharedPreferencesProvider.overrideWithValue(preferences),
      sessionStoreProvider.overrideWithValue(sessionStore),
      apiClientProvider.overrideWithValue(fakeClient(FakeAdapter(handler), sessionStore)),
      deviceIntegrityProvider.overrideWith((ref) async => DeviceIntegrity.unknown),
      phoneVerifierProvider.overrideWithValue(verifier ?? FakePhoneVerifier()),
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

void main() {
  test('usernames are normalised like the website', () {
    expect(normalizeUsername(' E2E Test A7! '), 'e2etesta7');
    expect(normalizeUsername('Ahmed.Ismail_1'), 'ahmed.ismail_1');
  });

  testWidgets('sign-up verifies the phone by SMS and creates the account', (tester) async {
    Object? registered;
    final verifier = FakePhoneVerifier();
    final store = MemorySessionStore();
    await pumpApp(
      tester,
      (request) async => switch (request.uri.path) {
        '/api/v1/auth/free-tier/public' => jsonBody(200, {
            'enabled': true,
            'plan': 'free',
            'consent_version': 'free-2026-11',
            'identity': {'minimum_age': 18, 'phone_verification_required': true},
          }),
        '/api/v1/auth/register/free' => () {
            registered = body(request);
            return jsonBody(201, grantJson());
          }(),
        '/api/v1/auth/refresh' || '/api/v1/auth/me' => jsonBody(401, {'detail': 'no session'}),
        _ => jsonBody(404, {'detail': 'not found'}),
      },
      store: store,
      verifier: verifier,
    );

    await tester.tap(find.byKey(const Key('create-account')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('register-name')), 'Test User');
    await tester.enterText(find.byKey(const Key('register-username')), 'Test.User');
    await tester.enterText(find.byKey(const Key('register-email')), 'test@example.com');
    await tester.enterText(find.byKey(const Key('register-password')), 'a-very-long-password');
    await tester.enterText(find.byKey(const Key('register-confirm')), 'a-very-long-password');
    await reveal(tester, find.byKey(const Key('register-birth')));
    await tester.tap(find.byKey(const Key('register-birth')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('register-country')), 'ae');
    await reveal(tester, find.byKey(const Key('register-phone')));
    await tester.enterText(find.byKey(const Key('register-phone')), '+971501234567');
    await tester.tap(find.byKey(const Key('register-send-code')));
    await tester.pumpAndSettle();
    expect(verifier.sent, ['+971501234567']);

    await tester.enterText(find.byKey(const Key('register-code')), '000000');
    await tester.tap(find.byKey(const Key('register-confirm-code')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('phone-error')), findsOneWidget);

    await tester.enterText(find.byKey(const Key('register-code')), '123456');
    await tester.tap(find.byKey(const Key('register-confirm-code')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('phone-verified')), findsOneWidget);

    await reveal(tester, find.byKey(const Key('register-consent')));
    await tester.tap(find.byKey(const Key('register-consent')));
    await tester.pump();
    await reveal(tester, find.byKey(const Key('register-submit')));
    await tester.tap(find.byKey(const Key('register-submit')));
    await tester.pumpAndSettle();

    final sent = registered! as Map;
    expect(sent['username'], 'test.user');
    expect(sent['country_code'], 'AE');
    expect(sent['phone_number'], '+971501234567');
    expect(sent['firebase_id_token'], 'f' * 200);
    expect(sent['consent_accepted'], true);
    expect(sent['consent_version'], 'free-2026-11');
    expect(sent['birth_date'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
    expect(store.refreshToken, 'refresh-1');
    expect(find.text('Welcome, Ahmed'), findsOneWidget);
  });

  testWidgets('sign-up waits for the phone before the account can be created', (tester) async {
    await pumpApp(
      tester,
      (request) async => request.uri.path.endsWith('/auth/free-tier/public')
          ? jsonBody(200, {
              'enabled': true,
              'consent_version': 'v1-test',
              'identity': {'minimum_age': 18, 'phone_verification_required': true},
            })
          : jsonBody(401, {'detail': 'no session'}),
    );
    await tester.tap(find.byKey(const Key('create-account')));
    await tester.pumpAndSettle();
    await reveal(tester, find.byKey(const Key('register-consent')));
    await tester.tap(find.byKey(const Key('register-consent')));
    await tester.pump();
    await reveal(tester, find.byKey(const Key('register-submit')));
    expect(tester.widget<FilledButton>(find.byKey(const Key('register-submit'))).onPressed, isNull);
  });

  testWidgets('a closed sign-up says so', (tester) async {
    await pumpApp(
      tester,
      (request) async => request.uri.path.endsWith('/auth/free-tier/public')
          ? jsonBody(200, {'enabled': false, 'consent_version': 'v1', 'identity': <String, Object?>{}})
          : jsonBody(401, {'detail': 'no session'}),
    );
    await tester.tap(find.byKey(const Key('create-account')));
    await tester.pumpAndSettle();
    expect(find.text('Free registration is currently disabled by the owner.'), findsOneWidget);
  });

  testWidgets('notifications: unread badge, read one, mark all read', (tester) async {
    final read = <String>{};
    final patches = <Object?>[];
    Map<String, Object?> n(String id, String title) => {
          'id': id,
          'title': title,
          'message': 'Body of $title',
          'severity': 'info',
          'read': read.contains(id),
          'archived': false,
          'created_at': '2026-11-23T10:00:00Z',
        };
    final reader = userJson(permissions: ['notifications:read', 'notifications:write']);
    final container = await pumpApp(
      tester,
      (request) async {
        final path = request.uri.path.replaceFirst('/api/v1', '');
        return switch ((request.method, path)) {
          ('POST', '/auth/refresh') => jsonBody(200, {...grantJson(), 'user': reader}),
          ('GET', '/auth/me') => jsonBody(200, reader),
          ('GET', '/notifications') => jsonBody(200, {
              'items': [n('n1', 'Project ready'), n('n2', 'Invoice paid')],
            }),
          ('PATCH', '/notifications/n1') => () {
              patches.add(body(request));
              read.add('n1');
              return jsonBody(200, n('n1', 'Project ready'));
            }(),
          ('POST', '/notifications/mark-all-read') => () {
              final count = 2 - read.length;
              read.addAll(['n1', 'n2']);
              return jsonBody(200, {'updated': count});
            }(),
          _ => jsonBody(404, {'detail': 'not found'}),
        };
      },
      store: MemorySessionStore(refreshToken: 'saved'),
    );

    expect(find.descendant(of: find.byKey(const Key('open-notifications')), matching: find.text('2')), findsOneWidget);
    container.read(routerProvider).go('/notifications');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Project ready'));
    await tester.pumpAndSettle();
    expect(patches, [
      {'read': true},
    ]);

    await tester.tap(find.byKey(const Key('mark-all-read')));
    await tester.pumpAndSettle();
    expect(find.text('Marked 1 notifications as read.'), findsOneWidget);
  });
}
