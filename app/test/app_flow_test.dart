import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

Future<ProviderContainer> pumpApp(
  WidgetTester tester, {
  required FakeAdapter adapter,
  required SessionStore store,
  String locale = 'ar',
}) async {
  SharedPreferences.setMockInitialValues({'aionex.locale': locale});
  final preferences = await SharedPreferences.getInstance();
  final container = ProviderContainer(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(preferences),
      sessionStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(fakeClient(adapter, store)),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
  await tester.pumpAndSettle();
  return container;
}

void main() {
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
}
