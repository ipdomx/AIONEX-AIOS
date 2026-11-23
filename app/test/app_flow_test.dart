import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:aionex/src/core/security/device_security.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

Future<ProviderContainer> pumpApp(
  WidgetTester tester, {
  required FakeAdapter adapter,
  required SessionStore store,
  String locale = 'ar',
  DeviceIntegrity integrity = DeviceIntegrity.unknown,
}) async {
  SharedPreferences.setMockInitialValues({'aionex.locale': locale});
  final preferences = await SharedPreferences.getInstance();
  final container = ProviderContainer(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(preferences),
      sessionStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(fakeClient(adapter, store)),
      deviceIntegrityProvider.overrideWith((ref) async => integrity),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
  await tester.pumpAndSettle();
  return container;
}

const securityChannel = MethodChannel('net.vipe.aionex/security');

void main() {
  final secureCalls = <Object?>[];
  setUp(() {
    secureCalls.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(securityChannel, (call) async {
      if (call.method == 'setSecure') secureCalls.add(call.arguments);
      return null;
    });
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(securityChannel, null);
  });

  testWidgets('Arabic sign-in is right-to-left and names a wrong password', (tester) async {
    final adapter = FakeAdapter((request) async => jsonBody(401, {'detail': 'Invalid credentials'}));
    await pumpApp(tester, adapter: adapter, store: MemorySessionStore());

    expect(find.text('تسجيل الدخول'), findsOneWidget);
    final direction = Directionality.of(tester.element(find.byKey(const Key('login-submit'))));
    expect(direction, TextDirection.rtl);

    await tester.enterText(find.byKey(const Key('login-email')), 'user@example.com');
    await tester.enterText(find.byKey(const Key('login-password')), 'wrong');
    await tester.tap(find.byKey(const Key('login-submit')));
    await tester.pumpAndSettle();

    expect(find.textContaining('البريد الإلكتروني أو كلمة المرور غير صحيحة'), findsOneWidget);
    expect(adapter.paths, ['/api/v1/auth/login']);
  });

  testWidgets('a good sign-in opens the dashboard and sign-out returns to sign-in', (tester) async {
    final store = MemorySessionStore();
    final adapter = FakeAdapter((request) async {
      return switch (request.uri.path) {
        '/api/v1/auth/login' => jsonBody(200, grantJson()),
        '/api/v1/auth/logout' => jsonBody(200, {'message': 'ok'}),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });
    await pumpApp(tester, adapter: adapter, store: store, locale: 'en');

    await tester.enterText(find.byKey(const Key('login-email')), 'user@example.com');
    await tester.enterText(find.byKey(const Key('login-password')), 'right');
    await tester.tap(find.byKey(const Key('login-submit')));
    await tester.pumpAndSettle();

    expect(find.text('Welcome, Ahmed'), findsOneWidget);
    // The sign-in screen was kept out of screenshots and released afterwards.
    expect(secureCalls, [true, false]);
    expect(find.byKey(const Key('device-compromised')), findsNothing);
    expect(Directionality.of(tester.element(find.text('Welcome, Ahmed'))), TextDirection.ltr);

    await tester.tap(find.text('Profile'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('sign-out')), 200);
    await tester.tap(find.byKey(const Key('sign-out')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('login-submit')), findsOneWidget);
    expect(store.refreshToken, isNull);
  });

  testWidgets('a saved session is restored on launch', (tester) async {
    final store = MemorySessionStore(refreshToken: 'saved');
    final adapter = FakeAdapter((request) async {
      return switch (request.uri.path) {
        '/api/v1/auth/refresh' => jsonBody(200, grantJson(access: 'fresh', refresh: 'rotated')),
        '/api/v1/auth/me' => jsonBody(200, userJson(name: 'Restored')),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });
    await pumpApp(tester, adapter: adapter, store: store, locale: 'en');

    expect(find.text('Welcome, Restored'), findsOneWidget);
    expect(adapter.paths, ['/api/v1/auth/refresh', '/api/v1/auth/me']);
    expect(store.refreshToken, 'rotated');
  });

  testWidgets('a modified device is told that payments are off', (tester) async {
    final store = MemorySessionStore(refreshToken: 'saved');
    final adapter = FakeAdapter((request) async {
      return switch (request.uri.path) {
        '/api/v1/auth/refresh' => jsonBody(200, grantJson()),
        '/api/v1/auth/me' => jsonBody(200, userJson()),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });
    await pumpApp(
      tester,
      adapter: adapter,
      store: store,
      locale: 'en',
      integrity: const DeviceIntegrity(compromised: true, emulator: false, debugBuild: false, signals: ['su_binary']),
    );

    expect(find.byKey(const Key('device-compromised')), findsOneWidget);
    expect(find.textContaining('payments are turned off'), findsOneWidget);
  });
}
