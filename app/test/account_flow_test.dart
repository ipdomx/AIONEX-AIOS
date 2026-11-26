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
import 'package:qr_flutter/qr_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

Future<ProviderContainer> pumpApp(WidgetTester tester, FakeAdapter adapter, SessionStore store) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
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

Object? body(RequestOptions request) => request.data is String ? jsonDecode(request.data as String) : request.data;

/// A signed-in user (restored from a saved refresh token).
Handler signedIn(Map<String, ResponseBody Function(RequestOptions)> routes) {
  return (request) async {
    final path = request.uri.path.replaceFirst('/api/v1', '');
    final key = '${request.method} $path';
    if (routes.containsKey(key)) return routes[key]!(request);
    return switch (path) {
      '/auth/refresh' => jsonBody(200, grantJson()),
      '/auth/me' => jsonBody(200, userJson()),
      '/auth/logout' => jsonBody(200, {'message': 'ok'}),
      '/settings' => jsonBody(200, settingsJson()),
      '/settings/sessions' => jsonBody(200, <Object>[]),
      _ => jsonBody(404, {'detail': 'not found'}),
    };
  };
}

Future<void> openSecurity(WidgetTester tester, ProviderContainer container) async {
  container.read(routerProvider).go('/profile/security');
  await tester.pumpAndSettle();
}

/// Scroll the visible list (not the off-stage tabs) until [finder] is on screen.
Future<void> reveal(WidgetTester tester, Finder finder) async {
  await tester.scrollUntilVisible(finder, 150, scrollable: find.byType(Scrollable).hitTestable().first);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('forgot password sends the email and never says whether it exists', (tester) async {
    final adapter = FakeAdapter((request) async {
      if (request.uri.path.endsWith('/auth/password-reset')) {
        expect(body(request), {'email': 'someone@example.com'});
        return jsonBody(202, {'message': 'accepted'});
      }
      return jsonBody(401, {'detail': 'no session'});
    });
    await pumpApp(tester, adapter, MemorySessionStore());

    await tester.tap(find.byKey(const Key('forgot-password')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('forgot-email')), ' someone@example.com ');
    await tester.tap(find.byKey(const Key('forgot-send')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('forgot-sent')), findsOneWidget);
  });

  testWidgets('the recovery link sets a new password, and an expired link says so', (tester) async {
    var calls = 0;
    final adapter = FakeAdapter((request) async {
      if (request.uri.path.endsWith('/auth/password-reset/confirm')) {
        calls++;
        expect(body(request), {'token': 't' * 32, 'new_password': 'a-new-long-password'});
        return calls == 1
            ? jsonBody(400, {'detail': 'Password reset token is invalid or expired'})
            : jsonBody(200, {'message': 'ok'});
      }
      return jsonBody(401, {'detail': 'no session'});
    });
    final container = await pumpApp(tester, adapter, MemorySessionStore());
    container.read(routerProvider).go('/reset-password?token=${'t' * 32}');
    await tester.pumpAndSettle();

    Future<void> submit() async {
      await tester.enterText(find.byKey(const Key('reset-password')), 'a-new-long-password');
      await tester.enterText(find.byKey(const Key('reset-confirm')), 'a-new-long-password');
      await tester.tap(find.byKey(const Key('reset-submit')));
      await tester.pumpAndSettle();
    }

    await submit();
    expect(find.text('The recovery link is invalid or expired.'), findsOneWidget);
    await submit();
    expect(find.byKey(const Key('reset-done')), findsOneWidget);
  });

  testWidgets('changing the password signs out and explains why', (tester) async {
    final store = MemorySessionStore(refreshToken: 'saved');
    final adapter = FakeAdapter(signedIn({
      'POST /settings/password': (request) {
        expect(body(request), {'current_password': 'old-password', 'new_password': 'brand-new-password'});
        return jsonBody(200, {'message': 'changed'});
      },
    }));
    final container = await pumpApp(tester, adapter, store);
    await openSecurity(tester, container);

    await tester.enterText(find.byKey(const Key('password-current')), 'old-password');
    await tester.enterText(find.byKey(const Key('password-new')), 'brand-new-password');
    await tester.enterText(find.byKey(const Key('password-confirm')), 'brand-new-password');
    await reveal(tester, find.byKey(const Key('password-submit')));
    await tester.tap(find.byKey(const Key('password-submit')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('login-notice')), findsOneWidget);
    expect(find.text('Your password was updated. You can sign in now.'), findsOneWidget);
    expect(store.refreshToken, isNull);
  });

  testWidgets('a short new password is stopped before reaching the server', (tester) async {
    final adapter = FakeAdapter(signedIn({}));
    final container = await pumpApp(tester, adapter, MemorySessionStore(refreshToken: 'saved'));
    await openSecurity(tester, container);

    await tester.enterText(find.byKey(const Key('password-current')), 'old-password');
    await tester.enterText(find.byKey(const Key('password-new')), 'short');
    await tester.enterText(find.byKey(const Key('password-confirm')), 'short');
    await reveal(tester, find.byKey(const Key('password-submit')));
    await tester.tap(find.byKey(const Key('password-submit')));
    await tester.pumpAndSettle();

    expect(find.text('Minimum 12 characters.'), findsOneWidget);
    expect(adapter.paths.where((path) => path.endsWith('/settings/password')), isEmpty);
  });

  testWidgets('two-factor setup shows the QR code and recovery codes, then verifies', (tester) async {
    var enabled = false;
    final adapter = FakeAdapter(signedIn({
      'POST /auth/mfa/setup': (_) => jsonBody(200, {
            'secret': 'JBSWY3DPEHPK3PXP',
            'qr_code': 'otpauth://totp/AIONEX:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=AIONEX',
            'backup_codes': ['aaaa-1111', 'bbbb-2222'],
          }),
      'POST /auth/mfa/verify': (request) {
        expect(body(request), {'code': '123456'});
        enabled = true;
        return jsonBody(200, {'enabled': true, 'backup_codes_remaining': 8, 'verified_at': null});
      },
      'GET /settings': (_) => jsonBody(200, settingsJson(mfa: enabled)),
    }));
    final container = await pumpApp(tester, adapter, MemorySessionStore(refreshToken: 'saved'));
    await openSecurity(tester, container);

    await tester.tap(find.byKey(const Key('mfa-enable')));
    await tester.pumpAndSettle();
    expect(find.byType(QrImageView), findsOneWidget);
    expect(find.text('JBSWY3DPEHPK3PXP'), findsOneWidget);
    expect(find.text('aaaa-1111'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('mfa-setup-code')), '123456');
    await reveal(tester, find.byKey(const Key('mfa-verify')));
    await tester.tap(find.byKey(const Key('mfa-verify')));
    await tester.pumpAndSettle();

    // The page is longer now (account deletion at the end): start from the top.
    await tester.drag(find.byType(Scrollable).hitTestable().first, const Offset(0, 4000));
    await tester.pumpAndSettle();
    await reveal(tester, find.text('Enabled — 8 recovery codes remaining'));
    expect(find.text('Enabled — 8 recovery codes remaining'), findsOneWidget);
    expect(find.byKey(const Key('mfa-disable')), findsOneWidget);
  });

  testWidgets('sessions are listed and an active one can be revoked', (tester) async {
    var revoked = false;
    final adapter = FakeAdapter(signedIn({
      'GET /settings/sessions': (_) => jsonBody(200, [
            {
              'id': 's-1',
              'created_at': '2026-11-20T10:00:00+00:00',
              'updated_at': '2026-11-20T10:00:00+00:00',
              'expires_at': '2026-12-20T10:00:00+00:00',
              'revoked_at': revoked ? '2026-11-23T10:00:00+00:00' : null,
              'active': !revoked,
              'ip_address': '203.0.113.7',
              'user_agent': 'Chrome on Android',
            },
          ]),
      'DELETE /settings/sessions/s-1': (_) {
        revoked = true;
        return jsonBody(200, {'revoked': true});
      },
    }));
    final container = await pumpApp(tester, adapter, MemorySessionStore(refreshToken: 'saved'));
    await openSecurity(tester, container);

    await reveal(tester, find.text('Chrome on Android'));
    expect(find.textContaining('Active'), findsOneWidget);
    await tester.tap(find.byTooltip('Revoke session'));
    await tester.pumpAndSettle();

    expect(revoked, isTrue);
    expect(find.textContaining('Closed'), findsOneWidget);
  });

  testWidgets('free accounts see the name locked, as the backend enforces', (tester) async {
    final adapter = FakeAdapter(signedIn({}));
    final container = await pumpApp(tester, adapter, MemorySessionStore(refreshToken: 'saved'));
    container.read(routerProvider).go('/profile');
    await tester.pumpAndSettle();

    final field = tester.widget<TextField>(find.byKey(const Key('profile-name')));
    expect(field.enabled, isFalse);
    expect(find.byKey(const Key('profile-save')), findsNothing);
    expect(find.textContaining('Free users may change only'), findsOneWidget);
  });
}
