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

Map<String, Object?> settings({bool mfa = false}) => {
      'id': 'u1',
      'email': 'ahmed@example.com',
      'name': 'Ahmed',
      'avatar': null,
      'role': 'Free User',
      'organization': {'id': 'o1', 'name': 'Personal', 'plan': 'Free'},
      'permissions': <String>[],
      'mfa_enabled': mfa,
      'mfa': {'enabled': mfa, 'backup_codes_remaining': 0},
      'passkeys': <Object>[],
      'free_tier': true,
      'profile_name_locked': true,
      'preferences': <String, Object>{},
    };

void main() {
  testWidgets('deleting the account needs the password and DELETE, then signs out', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.6;
    addTearDown(tester.view.reset);
    Object? sent;
    SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
    final preferences = await SharedPreferences.getInstance();
    final store = MemorySessionStore(refreshToken: 'saved');
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => sent == null ? jsonBody(200, grantJson()) : jsonBody(401, {'detail': 'gone'}),
        ('GET', '/auth/me') => jsonBody(200, userJson()),
        ('GET', '/settings') => jsonBody(200, settings()),
        ('GET', '/settings/sessions') => jsonBody(200, <Object>[]),
        ('GET', '/billing') => jsonBody(200, {
            'account': {'status': 'active', 'plan': 'free', 'limits': <String, Object>{}, 'usage': <String, Object>{}},
            'subscription': null,
            'invoices': <Object>[],
            'wallet': {'currency': 'USD', 'balance_minor': 0},
          }),
        ('POST', '/settings/account/delete') => () {
            sent = body(request);
            return jsonBody(200, {'deleted': true, 'subscription_cancelled': false, 'store_subscription_active': false});
          }(),
        ('POST', '/auth/logout') => jsonBody(200, {}),
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
    container.read(routerProvider).go('/profile/security');
    await tester.pumpAndSettle();

    final button = find.byKey(const Key('delete-account'));
    await tester.scrollUntilVisible(button, 300, scrollable: find.byType(Scrollable).hitTestable().first);
    expect(tester.widget<FilledButton>(button).onPressed, isNull);
    await tester.enterText(find.byKey(const Key('delete-password')), 'secret-pass');
    await tester.enterText(find.byKey(const Key('delete-confirm')), 'delete');
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(button).onPressed, isNull);
    await tester.enterText(find.byKey(const Key('delete-confirm')), 'DELETE');
    await tester.pumpAndSettle();
    await tester.tap(button);
    await tester.pumpAndSettle();

    expect(sent, {'current_password': 'secret-pass', 'mfa_code': null, 'confirm': 'DELETE'});
    expect(find.text('Your account was deleted. Thank you for using AIONEX.'), findsOneWidget);
  });
}
