import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Where the signed-in session lives.
///
/// * Android / iOS: the refresh token sits in the Keystore / Keychain and the
///   short-lived access token only in memory, so nothing usable is left in
///   plain files or backups.
/// * Web: the backend's httpOnly cookies carry the session and Dart never
///   holds a token, exactly like the current website.
abstract interface class SessionStore {
  bool get usesCookies;
  String? get accessToken;
  Future<String?> readRefreshToken();
  Future<void> save({required String accessToken, required String refreshToken});
  Future<void> clear();
}

SessionStore createSessionStore() => kIsWeb ? CookieSessionStore() : SecureSessionStore();

class SecureSessionStore implements SessionStore {
  SecureSessionStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(resetOnError: true),
              // ThisDeviceOnly: never synced to iCloud or restored onto another phone.
              iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
            );

  static const _refreshKey = 'aionex.refresh_token';
  final FlutterSecureStorage _storage;
  String? _accessToken;

  @override
  bool get usesCookies => false;

  @override
  String? get accessToken => _accessToken;

  @override
  Future<String?> readRefreshToken() async {
    try {
      return await _storage.read(key: _refreshKey);
    } on Exception {
      // A corrupted keystore entry must not trap the user: treat it as signed out.
      return null;
    }
  }

  @override
  Future<void> save({required String accessToken, required String refreshToken}) async {
    _accessToken = accessToken;
    await _storage.write(key: _refreshKey, value: refreshToken);
  }

  @override
  Future<void> clear() async {
    _accessToken = null;
    try {
      await _storage.delete(key: _refreshKey);
    } on Exception {
      // Nothing left to protect if the entry cannot be read either.
    }
  }
}

class CookieSessionStore implements SessionStore {
  @override
  bool get usesCookies => true;

  @override
  String? get accessToken => null;

  @override
  Future<String?> readRefreshToken() async => null;

  @override
  Future<void> save({required String accessToken, required String refreshToken}) async {}

  @override
  Future<void> clear() async {}
}

/// For tests only.
class MemorySessionStore implements SessionStore {
  MemorySessionStore({this.refreshToken, this.accessToken});

  String? refreshToken;

  @override
  String? accessToken;

  @override
  bool get usesCookies => false;

  @override
  Future<String?> readRefreshToken() async => refreshToken;

  @override
  Future<void> save({required String accessToken, required String refreshToken}) async {
    this.accessToken = accessToken;
    this.refreshToken = refreshToken;
  }

  @override
  Future<void> clear() async {
    accessToken = null;
    refreshToken = null;
  }
}
