import '../api/api_client.dart';
import '../api/api_exception.dart';
import 'models.dart';

/// The Super Owner signs in only through the private owner console.
class OwnerConsoleOnlyException implements Exception {
  const OwnerConsoleOnlyException();
}

/// Sign-in, session restore and sign-out against /api/v1/auth.
class AuthRepository {
  AuthRepository(this._api);

  final ApiClient _api;

  Future<LoginOutcome> login(String email, String password) async {
    final json = await _api.postForm('/auth/login', {'username': email.trim(), 'password': password});
    if (json['mfa_required'] == true) {
      final token = json['challenge_token'];
      if (token is! String || token.isEmpty) throw const FormatException('MFA challenge is incomplete');
      final seconds = json['expires_in'];
      return LoginNeedsMfa(
        MfaChallenge(challengeToken: token, expiresIn: Duration(seconds: seconds is num ? seconds.toInt() : 300)),
      );
    }
    return LoginSucceeded(await _accept(SessionGrant.fromJson(json)));
  }

  Future<RegistrationPolicy> registrationPolicy() async =>
      RegistrationPolicy.fromJson(await _api.getJson('/auth/free-tier/public', auth: false));

  /// Free sign-up; the response is a normal session, so the user is signed in.
  Future<AppUser> register(RegistrationForm form) async {
    final json = await _api.postJson('/auth/register/free', body: form.toJson(), auth: false, retry: false);
    return _accept(SessionGrant.fromJson(json));
  }

  Future<AppUser> completeMfa(MfaChallenge challenge, String code) async {
    final json = await _api.postJson(
      '/auth/mfa/challenge',
      body: {'challenge_token': challenge.challengeToken, 'code': code.trim()},
      auth: false,
      retry: false,
    );
    return _accept(SessionGrant.fromJson(json));
  }

  /// Bring back the previous session on launch, or null when there is none.
  Future<AppUser?> restore() async {
    final store = _api.store;
    if (!store.usesCookies) {
      if (await store.readRefreshToken() == null) return null;
      if (store.accessToken == null && !await _api.refreshSession()) return null;
    }
    try {
      return await currentUser();
    } on ApiException catch (error) {
      if (error.failure == ApiFailure.unauthorized) return null;
      rethrow;
    }
  }

  Future<AppUser> currentUser() async {
    final user = AppUser.fromJson(await _api.getJson('/auth/me'));
    if (user.isSuperOwner) {
      await _api.store.clear();
      throw const OwnerConsoleOnlyException();
    }
    return user;
  }

  /// Revoke the session on the server, then forget it locally whatever happens.
  Future<void> logout() async {
    final store = _api.store;
    final refreshToken = await store.readRefreshToken();
    try {
      await _api.postJson(
        '/auth/logout',
        body: refreshToken == null ? const <String, Object?>{} : {'refresh_token': refreshToken},
        retry: false,
      );
    } on ApiException {
      // Offline or already expired: the local copy is still removed below.
    } finally {
      await store.clear();
    }
  }

  Future<AppUser> _accept(SessionGrant grant) async {
    if (grant.user.isSuperOwner) {
      await _api.store.clear();
      throw const OwnerConsoleOnlyException();
    }
    await _api.store.save(accessToken: grant.accessToken, refreshToken: grant.refreshToken);
    return grant.user;
  }
}
