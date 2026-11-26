import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/providers.dart';

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;
DateTime? _d(Object? v) => v is String ? DateTime.tryParse(v) : null;
Map<String, Object?> _map(Object? v) => v is Map ? v.cast<String, Object?>() : const {};
List<Map<String, Object?>> _rows(Object? v) =>
    v is List ? [for (final r in v) if (r is Map) r.cast<String, Object?>()] : const [];

@immutable
class SecurityLabAccess {
  const SecurityLabAccess({
    required this.enabled,
    required this.granted,
    required this.reportsAvailable,
    required this.profiles,
    required this.maxTargets,
    required this.maxScansPerMonth,
    required this.scansThisMonth,
    required this.verifiedTargets,
    required this.reverifyDays,
  });

  final bool enabled;
  final bool granted;
  final bool reportsAvailable;
  final List<String> profiles;
  final int maxTargets;
  final int maxScansPerMonth;
  final int scansThisMonth;
  final int verifiedTargets;
  final int reverifyDays;

  bool get canRead => granted || reportsAvailable;

  factory SecurityLabAccess.fromJson(Map<String, Object?> j) {
    final limits = _map(j['limits']);
    final usage = _map(j['usage']);
    return SecurityLabAccess(
      enabled: j['enabled'] == true,
      granted: j['granted'] == true,
      reportsAvailable: j['reports_available'] == true,
      profiles: j['profiles'] is List ? (j['profiles']! as List).whereType<String>().toList() : const [],
      maxTargets: _i(limits['max_verified_targets']),
      maxScansPerMonth: _i(limits['max_scans_per_month']),
      scansThisMonth: _i(usage['scans_this_month']),
      verifiedTargets: _i(usage['verified_targets']),
      reverifyDays: _i(_map(j['verification'])['reverify_after_days']),
    );
  }
}

@immutable
class SecurityTarget {
  const SecurityTarget({required this.id, required this.origin, required this.status, required this.verifiedAt});
  final String id;
  final String origin;
  final String status;
  final DateTime? verifiedAt;

  bool get verified => status == 'verified' || verifiedAt != null && status != 'revoked';
  bool get removed => status == 'revoked';

  factory SecurityTarget.fromJson(Map<String, Object?> j) => SecurityTarget(
        id: _s(j['id']),
        origin: _s(j['origin']),
        status: _s(j['authorization_status'], _s(j['status'])),
        verifiedAt: _d(j['verified_at']),
      );
}

/// How to prove ownership: a file at a URL, or a DNS TXT record.
@immutable
class Verification {
  const Verification({
    required this.targetId,
    required this.challenge,
    required this.fileUrl,
    required this.fileContent,
    required this.dnsAvailable,
    required this.dnsName,
    required this.dnsValue,
  });
  final String targetId;
  final String challenge;
  final String fileUrl;
  final String fileContent;
  final bool dnsAvailable;
  final String? dnsName;
  final String dnsValue;

  factory Verification.fromJson(Map<String, Object?> j) {
    final v = _map(j['verification']);
    final methods = _map(v['methods']);
    final file = _map(methods['http_file']);
    final dns = _map(methods['dns_txt']);
    return Verification(
      targetId: _s(j['id']),
      challenge: _s(v['challenge']),
      fileUrl: _s(file['url'], _s(v['url'])),
      fileContent: _s(file['content'], _s(v['challenge'])),
      dnsAvailable: dns['available'] == true,
      dnsName: dns['record_name'] as String?,
      dnsValue: _s(dns['record_value']),
    );
  }
}

@immutable
class SecurityScan {
  const SecurityScan({
    required this.id,
    required this.targetId,
    required this.profile,
    required this.status,
    required this.findingCount,
    required this.severity,
    required this.errorMessage,
    required this.createdAt,
  });
  final String id;
  final String targetId;
  final String profile;
  final String status;
  final int findingCount;
  final Map<String, int> severity;
  final String? errorMessage;
  final DateTime? createdAt;

  bool get isActive => status == 'queued' || status == 'running';

  factory SecurityScan.fromJson(Map<String, Object?> j) {
    final summary = _map(j['summary']);
    return SecurityScan(
      id: _s(j['id']),
      targetId: _s(j['target_id']),
      profile: _s(j['profile']),
      status: _s(j['status']),
      findingCount: _i(summary['finding_count']),
      severity: {for (final e in _map(summary['severity']).entries) e.key: _i(e.value)},
      errorMessage: j['error_message'] as String?,
      createdAt: _d(j['created_at']),
    );
  }
}

@immutable
class SecurityFinding {
  const SecurityFinding({required this.id, required this.title, required this.severity, required this.category, required this.location, required this.remediation, required this.cwe});
  final String id;
  final String title;
  final String severity;
  final String category;
  final String? location;
  final String? remediation;
  final String? cwe;

  factory SecurityFinding.fromJson(Map<String, Object?> j) => SecurityFinding(
        id: _s(j['id']),
        title: _s(j['title']),
        severity: _s(j['severity'], 'info'),
        category: _s(j['category']),
        location: j['location'] as String?,
        remediation: j['remediation'] as String?,
        cwe: j['cwe'] as String?,
      );
}

/// The Security Lab, the same endpoints as vip-frontend/src/lib/api.ts.
class SecurityLabRepository {
  SecurityLabRepository(this._api);
  final ApiClient _api;

  Future<SecurityLabAccess> access() async => SecurityLabAccess.fromJson(await _api.getJson('/security-lab/access'));

  Future<List<SecurityTarget>> targets() async =>
      [for (final r in _rows(await _api.getList('/security-lab/targets'))) SecurityTarget.fromJson(r)];

  Future<Verification> addSite(String origin) async =>
      Verification.fromJson(await _api.postJson('/security-lab/targets/external', body: {'origin': origin.trim()}, retry: false));

  Future<SecurityTarget> verify(String targetId, String challenge, String method) async => SecurityTarget.fromJson(
        await _api.postJson('/security-lab/targets/${Uri.encodeComponent(targetId)}/verify',
            body: {'challenge': challenge, 'method': method}, retry: false),
      );

  Future<void> remove(String targetId) async => _api.deleteJson('/security-lab/targets/${Uri.encodeComponent(targetId)}');

  Future<List<SecurityScan>> scans() async =>
      [for (final r in _rows(await _api.getList('/security-lab/scans'))) SecurityScan.fromJson(r)];

  Future<SecurityScan> startScan(String targetId, String profile) async => SecurityScan.fromJson(
        await _api.postJson('/security-lab/scans', body: {'target_id': targetId, 'profile': profile}, retry: false),
      );

  Future<void> cancel(String scanId) async =>
      _api.postJson('/security-lab/scans/${Uri.encodeComponent(scanId)}/cancel', retry: false);

  Future<List<SecurityFinding>> findings(String scanId) async => [
        for (final r in _rows(await _api.getList('/security-lab/scans/${Uri.encodeComponent(scanId)}/findings')))
          SecurityFinding.fromJson(r),
      ];
}

final securityLabRepositoryProvider = Provider<SecurityLabRepository>((ref) => SecurityLabRepository(ref.watch(apiClientProvider)));
final securityAccessProvider = FutureProvider.autoDispose<SecurityLabAccess>((ref) => ref.watch(securityLabRepositoryProvider).access());
final securityTargetsProvider = FutureProvider.autoDispose<List<SecurityTarget>>((ref) => ref.watch(securityLabRepositoryProvider).targets());
final securityScansProvider = FutureProvider.autoDispose<List<SecurityScan>>((ref) => ref.watch(securityLabRepositoryProvider).scans());
final securityFindingsProvider =
    FutureProvider.autoDispose.family<List<SecurityFinding>, String>((ref, id) => ref.watch(securityLabRepositoryProvider).findings(id));
