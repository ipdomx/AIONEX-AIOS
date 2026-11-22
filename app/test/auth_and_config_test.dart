import 'package:aionex/src/core/auth/auth_repository.dart';
import 'package:aionex/src/core/auth/models.dart';
import 'package:aionex/src/core/auth/session_controller.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/config/app_config.dart';
import 'package:aionex/src/core/locale/locale_controller.dart';
import 'package:aionex/src/core/router/app_router.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_api.dart';

void main() {
  group('API base', () {
    test('accepts https and strips the trailing slash', () {
      expect(parseApiBase('https://api.vip-e.net/api/v1/').toString(), 'https://api.vip-e.net/api/v1');
    });

    test('rejects plain http outside a local debug server', () {
      expect(() => parseApiBase('http://api.vip-e.net/api/v1'), throwsArgumentError);
      expect(() => parseApiBase('http://localhost:8000/api/v1'), throwsArgumentError);
      expect(parseApiBase('http://localhost:8000/api/v1', allowInsecureLocal: true).host, 'localhost');
    });

    test('rejects credentials, queries and relative values', () {
      expect(() => parseApiBase('https://user:pw@api.vip-e.net/api/v1'), throwsArgumentError);
      expect(() => parseApiBase('https://api.vip-e.net/api/v1?x=1'), throwsArgumentError);
      expect(() => parseApiBase('/api/v1'), throwsArgumentError);
    });
  });

  group('sign-in', () {
    test('posts the form fields and keeps the token pair', () async {
      final store = MemorySessionStore();
      final adapter = FakeAdapter((request) async {
        expect(request.data, {'username': 'user@example.com', 'password': 'pw'});
        expect(request.headers['Authorization'], isNull);
        return jsonBody(200, grantJson());
      });
      final outcome = await AuthRepository(fakeClient(adapter, store)).login(' user@example.com ', 'pw');

      expect(outcome, isA<LoginSucceeded>());
      expect(store.accessToken, 'access-1');
      expect(store.refreshToken, 'refresh-1');
    });

    test('returns the MFA challenge without storing anything', () async {
      final store = MemorySessionStore();
      final adapter = FakeAdapter(
        (request) async => jsonBody(200, {'mfa_required': true, 'challenge_token': 'c' * 30, 'expires_in': 300}),
      );
      final outcome = await AuthRepository(fakeClient(adapter, store)).login('user@example.com', 'pw');

      expect(outcome, isA<LoginNeedsMfa>());
      expect(store.refreshToken, isNull);
    });

    test('refuses the Super Owner and leaves no session behind', () async {
      final store = MemorySessionStore();
      final adapter = FakeAdapter((request) async => jsonBody(200, grantJson(role: 'Super Owner')));

      await expectLater(
        AuthRepository(fakeClient(adapter, store)).login('owner@example.com', 'pw'),
        throwsA(isA<OwnerConsoleOnlyException>()),
      );
      expect(store.refreshToken, isNull);
    });

    test('sign-out revokes the refresh token and clears it even offline', () async {
      final store = MemorySessionStore(accessToken: 'a', refreshToken: 'r');
      final adapter = FakeAdapter((request) async => jsonBody(503, {'detail': 'down'}));
      await AuthRepository(fakeClient(adapter, store)).logout();

      expect(adapter.requests.single.data, {'refresh_token': 'r'});
      expect(store.refreshToken, isNull);
    });
  });

  group('routing', () {
    const user = SignedIn(
      AppUser(
        id: 'u',
        email: 'e@x.y',
        name: 'n',
        role: 'Free User',
        status: 'active',
        permissions: [],
        organizationId: 'o',
        organizationName: 'O',
        organizationPlan: 'Free',
      ),
    );

    test('waits on the splash screen while the session loads or fails', () {
      expect(redirectFor(const AsyncLoading<SessionState>(), '/'), '/splash');
      expect(redirectFor(AsyncError<SessionState>(Exception(), StackTrace.empty), '/profile'), '/splash');
      expect(redirectFor(const AsyncLoading<SessionState>(), '/splash'), isNull);
    });

    test('keeps signed-out users on the sign-in pages', () {
      expect(redirectFor(const AsyncData<SessionState>(SignedOut()), '/'), '/login');
      expect(redirectFor(const AsyncData<SessionState>(SignedOut()), '/login/mfa'), isNull);
    });

    test('sends signed-in users into the workspace', () {
      expect(redirectFor(const AsyncData<SessionState>(user), '/login'), '/');
      expect(redirectFor(const AsyncData<SessionState>(user), '/splash'), '/');
      expect(redirectFor(const AsyncData<SessionState>(user), '/profile'), isNull);
    });
  });

  test('device languages resolve to one of the six, defaulting to Arabic', () {
    expect(resolveLocale(const [Locale('fr', 'CA')]), const Locale('fr'));
    expect(resolveLocale(const [Locale('ja'), Locale('tr')]), const Locale('tr'));
    expect(resolveLocale(const [Locale('ja')]), const Locale('ar'));
    expect(resolveLocale(null), const Locale('ar'));
  });
}
