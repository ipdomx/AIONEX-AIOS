import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/providers.dart';

/// GET/PATCH /settings: the account as the profile screen shows it.
@immutable
class AccountSettings {
  const AccountSettings({
    required this.name,
    required this.email,
    required this.role,
    required this.organization,
    required this.avatar,
    required this.mfaEnabled,
    required this.backupCodesRemaining,
    required this.activeSessions,
    required this.passwordMinLength,
  });

  final String name;
  final String email;
  final String role;
  final String organization;

  /// A data: URL (PNG, JPEG, WebP or GIF) or null.
  final String? avatar;
  final bool mfaEnabled;
  final int backupCodesRemaining;
  final int activeSessions;
  final int passwordMinLength;

  /// Free accounts may change only the picture and the password (backend rule).
  bool get canEditName => role != 'Free User';

  factory AccountSettings.fromJson(Map<String, Object?> json) {
    final profile = _map(json['profile']);
    final security = _map(json['security']);
    return AccountSettings(
      name: (profile['name'] as String?) ?? '',
      email: (profile['email'] as String?) ?? '',
      role: (profile['role'] as String?) ?? '',
      organization: (profile['organization'] as String?) ?? '',
      avatar: profile['avatar'] as String?,
      mfaEnabled: security['mfa_enabled'] == true,
      backupCodesRemaining: _int(security['mfa_backup_codes_remaining']),
      activeSessions: _int(security['active_sessions']),
      passwordMinLength: _int(security['password_min_length'], fallback: 12),
    );
  }
}

@immutable
class MfaSetup {
  const MfaSetup({required this.secret, required this.otpauthUri, required this.backupCodes});

  final String secret;

  /// otpauth://totp/… for the QR code and "open in authenticator".
  final String otpauthUri;
  final List<String> backupCodes;
}

@immutable
class AccountSession {
  const AccountSession({
    required this.id,
    required this.createdAt,
    required this.active,
    this.ipAddress,
    this.userAgent,
  });

  final String id;
  final DateTime? createdAt;
  final bool active;
  final String? ipAddress;
  final String? userAgent;

  factory AccountSession.fromJson(Map<String, Object?> json) => AccountSession(
        id: (json['id'] as String?) ?? '',
        createdAt: DateTime.tryParse((json['created_at'] as String?) ?? ''),
        active: json['active'] == true,
        ipAddress: json['ip_address'] as String?,
        userAgent: json['user_agent'] as String?,
      );
}

/// Profile, password, MFA, sessions and password recovery (/settings, /auth).
class AccountRepository {
  AccountRepository(this._api);

  final ApiClient _api;

  Future<AccountSettings> settings() async => AccountSettings.fromJson(await _api.getJson('/settings'));

  Future<AccountSettings> update({String? name, String? avatar}) async {
    final body = <String, Object?>{'name': ?name, 'avatar': ?avatar};
    return AccountSettings.fromJson(await _api.patchJson('/settings', body: body));
  }

  /// The server revokes every session afterwards, so the caller signs out.
  Future<void> changePassword(String current, String next) async {
    await _api.postJson('/settings/password', body: {'current_password': current, 'new_password': next});
  }

  Future<MfaSetup> startMfaSetup() async {
    final json = await _api.postJson('/auth/mfa/setup');
    final codes = json['backup_codes'];
    return MfaSetup(
      secret: (json['secret'] as String?) ?? '',
      otpauthUri: (json['qr_code'] as String?) ?? '',
      backupCodes: codes is List ? codes.whereType<String>().toList(growable: false) : const [],
    );
  }

  Future<void> verifyMfaSetup(String code) async {
    await _api.postJson('/auth/mfa/verify', body: {'code': code.trim()});
  }

  /// The server revokes every session afterwards, so the caller signs out.
  Future<void> disableMfa(String currentPassword, String code) async {
    await _api.postJson('/auth/mfa/disable', body: {'current_password': currentPassword, 'code': code.trim()});
  }

  Future<List<AccountSession>> sessions() async {
    final rows = await _api.getList('/settings/sessions');
    return [
      for (final row in rows)
        if (row is Map) AccountSession.fromJson(row.cast<String, Object?>()),
    ];
  }

  Future<void> revokeSession(String id) async {
    await _api.deleteJson('/settings/sessions/${Uri.encodeComponent(id)}');
  }

  /// Always "accepted": the server never says whether the email exists.
  Future<void> requestPasswordReset(String email) async {
    await _api.postJson('/auth/password-reset', body: {'email': email.trim()}, auth: false, retry: false);
  }

  Future<void> confirmPasswordReset(String token, String newPassword) async {
    await _api.postJson(
      '/auth/password-reset/confirm',
      body: {'token': token, 'new_password': newPassword},
      auth: false,
      retry: false,
    );
  }
}

Map<Object?, Object?> _map(Object? value) => value is Map ? value : const {};

int _int(Object? value, {int fallback = 0}) => value is num ? value.toInt() : fallback;

final accountRepositoryProvider = Provider<AccountRepository>((ref) => AccountRepository(ref.watch(apiClientProvider)));

final accountSettingsProvider = FutureProvider.autoDispose<AccountSettings>(
  (ref) => ref.watch(accountRepositoryProvider).settings(),
);

final accountSessionsProvider = FutureProvider.autoDispose<List<AccountSession>>(
  (ref) => ref.watch(accountRepositoryProvider).sessions(),
);
