import 'package:flutter/foundation.dart';

/// Build-time settings. Nothing secret lives here: the app ships to users, so
/// every value below is public by design (see docs/project/COMPLETION-ROADMAP.md, N-02).
@immutable
class AppConfig {
  const AppConfig({required this.apiBaseUrl, required this.appVersion});

  /// Root of the public API, without a trailing slash, e.g. https://api.vip-e.net/api/v1.
  final Uri apiBaseUrl;

  /// Sent as X-AIOS-Client so the backend can tell app traffic apart.
  final String appVersion;

  static const _defaultApiBase = 'https://api.vip-e.net/api/v1';

  factory AppConfig.fromEnvironment() {
    const raw = String.fromEnvironment('AIONEX_API_BASE', defaultValue: _defaultApiBase);
    const version = String.fromEnvironment('AIONEX_APP_VERSION', defaultValue: '0.1.0');
    return AppConfig(apiBaseUrl: parseApiBase(raw, allowInsecureLocal: kDebugMode), appVersion: version);
  }
}

/// Accept only HTTPS endpoints. Plain HTTP is allowed solely for a local
/// development server in debug builds, never in a release build.
Uri parseApiBase(String raw, {bool allowInsecureLocal = false}) {
  final uri = Uri.tryParse(raw.trim());
  if (uri == null || !uri.hasAuthority || uri.host.isEmpty) {
    throw ArgumentError.value(raw, 'AIONEX_API_BASE', 'is not an absolute URL');
  }
  if (uri.hasQuery || uri.hasFragment || uri.userInfo.isNotEmpty) {
    throw ArgumentError.value(raw, 'AIONEX_API_BASE', 'must not carry credentials, a query or a fragment');
  }
  final local = uri.host == 'localhost' || uri.host == '127.0.0.1' || uri.host == '10.0.2.2';
  final secure = uri.scheme == 'https';
  if (!secure && !(allowInsecureLocal && local && uri.scheme == 'http')) {
    throw ArgumentError.value(raw, 'AIONEX_API_BASE', 'must use https');
  }
  final path = uri.path.endsWith('/') ? uri.path.substring(0, uri.path.length - 1) : uri.path;
  return uri.replace(path: path);
}
