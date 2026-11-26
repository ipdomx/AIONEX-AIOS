import 'dart:convert';

import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/firebase/firebase_setup.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:aionex/src/core/router/app_router.dart';
import 'package:aionex/src/core/security/device_security.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

class FakeSocialSigner implements SocialSigner {
  final asked = <String>[];
  bool cancel = false;

  @override
  Future<String> idToken(String firebaseProvider) async {
    asked.add(firebaseProvider);
    if (cancel) throw const SocialSignInCancelled();
    return 't' * 150;
  }
}

Object? body(RequestOptions request) => request.data is String ? jsonDecode(request.data as String) : request.data;

final socialConfig = {
  'provider': 'firebase',
  'enabled': true,
  'providers': [
    {'id': 'google', 'label': 'Google', 'firebase_provider': 'google.com', 'enabled': true},
    {'id': 'apple', 'label': 'Apple', 'firebase_provider': 'apple.com', 'enabled': true},
    {'id': 'x', 'label': 'X', 'firebase_provider': 'twitter.com', 'enabled': true},
  ],
};

Future<ProviderContainer> pumpApp(
  WidgetTester tester,
  Handler handler, {
  required SocialSigner signer,
  SessionStore? store,
  bool firebaseReady = true,
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
      firebaseReadyProvider.overrideWith((ref) async => firebaseReady),
      socialSignerProvider.overrideWithValue(signer),
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
  testWidgets('only providers the phone supports are offered, and Google signs in', (tester) async {
    final signer = FakeSocialSigner();
    final store = MemorySessionStore();
    Object? exchanged;
    await pumpApp(
      tester,
      (request) async => switch (request.uri.path) {
        '/api/v1/auth/firebase/social/public' => jsonBody(200, socialConfig),
        '/api/v1/auth/firebase/social/session' => () {
            exchanged = body(request);
            return jsonBody(200, grantJson());
          }(),
        _ => jsonBody(401, {'detail': 'no session'}),
      },
      signer: signer,
      store: store,
    );
    expect(find.byKey(const Key('social-google')), findsOneWidget);
    expect(find.byKey(const Key('social-apple')), findsOneWidget);
    expect(find.byKey(const Key('social-x')), findsNothing);

    await tapVisible(tester, find.byKey(const Key('social-google')));
    expect(signer.asked, ['google.com']);
    expect((exchanged! as Map)['id_token'], 't' * 150);
    expect(store.refreshToken, 'refresh-1');
    expect(find.text('Welcome, Ahmed'), findsOneWidget);
  });

  testWidgets('an account with two-step verification goes to the code screen', (tester) async {
    final store = MemorySessionStore();
    await pumpApp(
      tester,
      (request) async => switch (request.uri.path) {
        '/api/v1/auth/firebase/social/public' => jsonBody(200, socialConfig),
        '/api/v1/auth/firebase/social/session' =>
          jsonBody(200, {'mfa_required': true, 'challenge_token': 'c' * 40, 'expires_in': 300}),
        _ => jsonBody(401, {'detail': 'no session'}),
      },
      signer: FakeSocialSigner(),
      store: store,
    );
    await tapVisible(tester, find.byKey(const Key('social-apple')));
    expect(store.refreshToken, isNull);
    expect(find.byKey(const Key('mfa-code')), findsOneWidget);
  });

  testWidgets('a new Google identity continues to sign-up with its email fixed', (tester) async {
    Object? registered;
    await pumpApp(
      tester,
      (request) async => switch (request.uri.path) {
        '/api/v1/auth/firebase/social/public' => jsonBody(200, socialConfig),
        '/api/v1/auth/firebase/social/session' => jsonBody(409, {
            'detail': {'code': 'ACCOUNT_REGISTRATION_REQUIRED', 'message': 'Create your AIOS account first.'},
          }),
        '/api/v1/auth/firebase/social/registration/prepare' => jsonBody(200, {
            'registration_token': 'r' * 40,
            'provider': 'google',
            'email': 'new.person@gmail.com',
            'name': 'New Person',
            'expires_in': 900,
          }),
        '/api/v1/auth/free-tier/public' => jsonBody(200, {
            'enabled': true,
            'consent_version': 'free-2026-11',
            'identity': {'minimum_age': 18, 'phone_verification_required': false},
          }),
        '/api/v1/auth/register/free' => () {
            registered = body(request);
            return jsonBody(201, grantJson());
          }(),
        _ => jsonBody(401, {'detail': 'no session'}),
      },
      signer: FakeSocialSigner(),
    );
    await tapVisible(tester, find.byKey(const Key('social-google')));
    expect(find.byKey(const Key('register-social-note')), findsOneWidget);
    final email = tester.widget<EditableText>(
      find.descendant(of: find.byKey(const Key('register-email')), matching: find.byType(EditableText)),
    );
    expect(email.controller.text, 'new.person@gmail.com');
    expect(email.readOnly, isTrue);

    await tester.enterText(find.byKey(const Key('register-username')), 'new.person');
    await tester.enterText(find.byKey(const Key('register-password')), 'a-very-long-password');
    await tester.enterText(find.byKey(const Key('register-confirm')), 'a-very-long-password');
    await tapVisible(tester, find.byKey(const Key('register-birth')));
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('register-country')));
    await tester.enterText(find.byKey(const Key('register-country')), 'eg');
    await tapVisible(tester, find.byKey(const Key('register-consent')));
    await tapVisible(tester, find.byKey(const Key('register-submit')));

    final sent = registered! as Map;
    expect(sent['email'], 'new.person@gmail.com');
    expect(sent['social_registration_token'], 'r' * 40);
    expect(find.text('Welcome, Ahmed'), findsOneWidget);
  });

  testWidgets('closing the provider sheet changes nothing', (tester) async {
    final signer = FakeSocialSigner()..cancel = true;
    await pumpApp(
      tester,
      (request) async => request.uri.path.endsWith('/social/public')
          ? jsonBody(200, socialConfig)
          : jsonBody(401, {'detail': 'no session'}),
      signer: signer,
    );
    await tapVisible(tester, find.byKey(const Key('social-google')));
    expect(find.byKey(const Key('login-error')), findsNothing);
    expect(find.byKey(const Key('login-submit')), findsOneWidget);
  });

  testWidgets('without Firebase in the build there are no provider buttons', (tester) async {
    await pumpApp(
      tester,
      (request) async => request.uri.path.endsWith('/social/public')
          ? jsonBody(200, socialConfig)
          : jsonBody(401, {'detail': 'no session'}),
      signer: FakeSocialSigner(),
      firebaseReady: false,
    );
    expect(find.byKey(const Key('social-google')), findsNothing);
  });
}
