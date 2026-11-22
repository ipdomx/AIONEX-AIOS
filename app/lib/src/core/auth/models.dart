import 'package:flutter/foundation.dart';

/// The signed-in user, as returned by /auth/me and the login endpoints.
@immutable
class AppUser {
  const AppUser({
    required this.id,
    required this.email,
    required this.name,
    required this.role,
    required this.status,
    required this.permissions,
    required this.organizationId,
    required this.organizationName,
    required this.organizationPlan,
    this.avatar,
  });

  final String id;
  final String email;
  final String name;
  final String role;
  final String status;
  final List<String> permissions;
  final String organizationId;
  final String organizationName;
  final String organizationPlan;
  final String? avatar;

  /// The Super Owner uses the private owner console, never the public app.
  bool get isSuperOwner => role == 'Super Owner';

  factory AppUser.fromJson(Map<String, Object?> json) {
    final organization = json['organization'];
    final org = organization is Map ? organization : const <Object?, Object?>{};
    final permissions = json['permissions'];
    return AppUser(
      id: _required(json, 'id'),
      email: _required(json, 'email'),
      name: (json['name'] as String?) ?? '',
      role: (json['role'] as String?) ?? '',
      status: (json['status'] as String?) ?? '',
      permissions: permissions is List ? permissions.whereType<String>().toList(growable: false) : const [],
      organizationId: (org['id'] as String?) ?? '',
      organizationName: (org['name'] as String?) ?? '',
      organizationPlan: (org['plan'] as String?) ?? '',
      avatar: json['avatar'] as String?,
    );
  }

  static String _required(Map<String, Object?> json, String key) {
    final value = json[key];
    if (value is String && value.isNotEmpty) return value;
    throw FormatException('user.$key is missing');
  }
}

/// A completed sign-in: a token pair plus the user.
@immutable
class SessionGrant {
  const SessionGrant({required this.accessToken, required this.refreshToken, required this.user});

  final String accessToken;
  final String refreshToken;
  final AppUser user;

  factory SessionGrant.fromJson(Map<String, Object?> json) {
    final user = json['user'];
    final access = json['access_token'];
    final refresh = json['refresh_token'];
    if (access is! String || refresh is! String || user is! Map<String, Object?>) {
      throw const FormatException('login response is incomplete');
    }
    return SessionGrant(accessToken: access, refreshToken: refresh, user: AppUser.fromJson(user));
  }
}

/// Sign-in needs a second factor before a session is issued.
@immutable
class MfaChallenge {
  const MfaChallenge({required this.challengeToken, required this.expiresIn});

  final String challengeToken;
  final Duration expiresIn;
}

/// The result of the email/password step.
sealed class LoginOutcome {
  const LoginOutcome();
}

final class LoginSucceeded extends LoginOutcome {
  const LoginSucceeded(this.user);
  final AppUser user;
}

final class LoginNeedsMfa extends LoginOutcome {
  const LoginNeedsMfa(this.challenge);
  final MfaChallenge challenge;
}
