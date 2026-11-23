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

/// GET /auth/free-tier/public: what free sign-up requires right now (owner-set).
@immutable
class RegistrationPolicy {
  const RegistrationPolicy({
    required this.enabled,
    required this.consentVersion,
    required this.minimumAge,
    required this.phoneRequired,
  });

  final bool enabled;
  final String consentVersion;
  final int minimumAge;
  final bool phoneRequired;

  factory RegistrationPolicy.fromJson(Map<String, Object?> json) {
    final identity = json['identity'];
    final id = identity is Map ? identity : const <Object?, Object?>{};
    final age = id['minimum_age'];
    return RegistrationPolicy(
      enabled: json['enabled'] == true,
      consentVersion: (json['consent_version'] as String?) ?? '',
      minimumAge: age is num ? age.toInt() : 18,
      phoneRequired: id['phone_verification_required'] != false,
    );
  }
}

/// The free sign-up form (POST /auth/register/free).
@immutable
class RegistrationForm {
  const RegistrationForm({
    required this.username,
    required this.name,
    required this.email,
    required this.password,
    required this.birthDate,
    required this.countryCode,
    required this.phoneNumber,
    required this.firebaseIdToken,
    required this.consentVersion,
    required this.telemetry,
  });

  final String username;
  final String name;
  final String email;
  final String password;
  final DateTime birthDate;
  final String countryCode;
  final String phoneNumber;
  final String? firebaseIdToken;
  final String consentVersion;
  final Map<String, Object?> telemetry;

  Map<String, Object?> toJson() => {
        'username': username,
        'name': name.trim(),
        'email': email.trim(),
        'password': password,
        'birth_date': '${birthDate.year.toString().padLeft(4, '0')}-'
            '${birthDate.month.toString().padLeft(2, '0')}-${birthDate.day.toString().padLeft(2, '0')}',
        'country_code': countryCode.toUpperCase(),
        'phone_number': phoneNumber,
        'firebase_id_token': ?firebaseIdToken,
        'consent_accepted': true,
        'consent_version': consentVersion,
        'telemetry': telemetry,
      };
}
