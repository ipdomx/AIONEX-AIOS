// Contract check against the real backend. Skipped unless the environment
// provides a dedicated test account:
//   AIONEX_LIVE_EMAIL, AIONEX_LIVE_PASSWORD [, AIONEX_LIVE_API]
// Never point it at a personal account; the password is never printed.
@Tags(['live'])
library;

import 'dart:io';

import 'package:aionex/src/core/api/api_client.dart';
import 'package:aionex/src/core/api/api_exception.dart';
import 'package:aionex/src/core/auth/auth_repository.dart';
import 'package:aionex/src/core/auth/models.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/config/app_config.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final email = Platform.environment['AIONEX_LIVE_EMAIL'];
  final password = Platform.environment['AIONEX_LIVE_PASSWORD'];
  final skip = email == null || password == null ? 'live account not configured' : null;
  final config = AppConfig(
    apiBaseUrl: parseApiBase(Platform.environment['AIONEX_LIVE_API'] ?? 'https://api.vip-e.net/api/v1'),
    appVersion: 'live-test',
  );

  test('wrong password is a 401 the app reports as invalid credentials', () async {
    final repo = AuthRepository(ApiClient(config: config, store: MemorySessionStore()));
    await expectLater(
      repo.login(email!, 'definitely-not-the-password'),
      throwsA(isA<ApiException>().having((e) => e.failure, 'failure', ApiFailure.unauthorized)),
    );
  }, skip: skip);

  test('sign in, read the account, refresh, restore and sign out', () async {
    final store = MemorySessionStore();
    final client = ApiClient(config: config, store: store);
    final repo = AuthRepository(client);

    final outcome = await repo.login(email!, password!);
    expect(outcome, isA<LoginSucceeded>());
    final user = (outcome as LoginSucceeded).user;
    expect(user.email, email);
    expect(user.isSuperOwner, isFalse);
    expect(store.refreshToken, isNotNull);

    final firstRefresh = store.refreshToken;
    expect(await client.refreshSession(), isTrue);
    expect(store.refreshToken, isNot(firstRefresh), reason: 'refresh tokens rotate');

    // A cold start: only the refresh token survives, as on a phone.
    store.accessToken = null;
    final restored = await repo.restore();
    expect(restored?.id, user.id);

    final revoked = store.refreshToken;
    await repo.logout();
    expect(store.refreshToken, isNull);

    // The revoked token must not come back to life.
    final stale = MemorySessionStore(refreshToken: revoked);
    expect(await ApiClient(config: config, store: stale).refreshSession(), isFalse);
  }, skip: skip);
}
