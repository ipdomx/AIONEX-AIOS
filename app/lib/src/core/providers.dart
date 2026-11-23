import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api/api_client.dart';
import 'api/api_exception.dart';
import 'auth/auth_repository.dart';
import 'auth/session_store.dart';
import 'config/app_config.dart';

final appConfigProvider = Provider<AppConfig>((ref) => AppConfig.fromEnvironment());

final sessionStoreProvider = Provider<SessionStore>((ref) => createSessionStore());

/// The root CAs the phone apps trust for the API (assets/security/api_roots.crt),
/// loaded in main(). Null on the web, where the browser checks certificates.
final pinnedRootsProvider = Provider<List<int>?>((ref) => null);

final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(
    config: ref.watch(appConfigProvider),
    store: ref.watch(sessionStoreProvider),
    trustedRoots: ref.watch(pinnedRootsProvider),
  );
});

final authRepositoryProvider = Provider<AuthRepository>((ref) => AuthRepository(ref.watch(apiClientProvider)));

/// Loaded once in main() and injected with an override.
final sharedPreferencesProvider = Provider<SharedPreferences>((ref) {
  throw StateError('sharedPreferencesProvider must be overridden at startup');
});

/// Riverpod's automatic retry, limited to dropped connections: a 4xx answer
/// (not found, forbidden, …) will not change by asking again.
Duration? retryOnlyNetworkErrors(int retryCount, Object error) {
  if (retryCount >= 3 || error is! ApiException || error.failure != ApiFailure.network) return null;
  return Duration(seconds: 2 << retryCount);
}
