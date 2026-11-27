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
    this.source,
  });

  /// subscription, owner, grant… The engine inventory is not shown to subscribers (as on the website).
  final String? source;
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
      source: j['source'] as String?,
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
  const SecurityFinding({required this.id, required this.title, required this.severity, required this.category, required this.location, required this.remediation, required this.cwe, this.state = ''});
  final String id;

  /// Only "confirmed" findings can enter remediation (the server enforces it).
  final String state;
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
        state: _s(j['state']),
      );
}

/// A scanner engine and whether the worker reports it available.
@immutable
class SecurityTool {
  const SecurityTool({required this.id, required this.category, required this.available, required this.active, required this.requiresClone});
  final String id;
  final String category;
  final bool available;
  final bool active;
  final bool requiresClone;

  factory SecurityTool.fromJson(Map<String, Object?> j) => SecurityTool(
        id: _s(j['id']),
        category: _s(j['category']),
        available: j['available'] == true,
        active: j['active'] == true,
        requiresClone: j['requires_clone'] == true,
      );
}

/// Evidence-gated remediation of one finding (managed AIONEX projects only).
@immutable
class SecurityRemediation {
  const SecurityRemediation({required this.id, required this.findingId, required this.status, required this.updatedAt});
  final String id;
  final String findingId;
  final String status;
  final DateTime? updatedAt;

  bool get canRetest => status == 'regression_passed';
  bool get canFinalize => status == 'retest_queued';

  factory SecurityRemediation.fromJson(Map<String, Object?> j) => SecurityRemediation(
        id: _s(j['id']),
        findingId: _s(j['finding_id']),
        status: _s(j['status']),
        updatedAt: _d(j['updated_at']),
      );
}

/// The printable report: target, dates and counts per severity.
@immutable
class SecurityReport {
  const SecurityReport({
    required this.origin,
    required this.profile,
    required this.completedAt,
    required this.generatedAt,
    required this.counts,
  });
  final String? origin;
  final String profile;
  final DateTime? completedAt;
  final DateTime? generatedAt;
  final Map<String, int> counts;

  factory SecurityReport.fromJson(Map<String, Object?> j) {
    final scan = _map(j['scan']);
    final target = j['target'] is Map ? _map(j['target']) : null;
    return SecurityReport(
      origin: target == null ? null : _s(target['origin']),
      profile: _s(scan['profile']),
      completedAt: _d(scan['completed_at']),
      generatedAt: _d(j['generated_at']),
      counts: {for (final e in _map(j['severity_counts']).entries) e.key: _i(e.value)},
    );
  }
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

extension SecurityLabExtras on SecurityLabRepository {
  ApiClient get _client => _api;

  Future<List<SecurityTool>> tools() async =>
      [for (final r in _rows(await _client.getList('/security-lab/tools'))) SecurityTool.fromJson(r)];

  Future<SecurityReport> report(String scanId) async =>
      SecurityReport.fromJson(await _client.getJson('/security-lab/scans/${Uri.encodeComponent(scanId)}/report'));

  Future<List<SecurityRemediation>> remediations() async =>
      [for (final r in _rows(await _client.getList('/security-lab/remediations'))) SecurityRemediation.fromJson(r)];

  Future<void> requestRemediation(String findingId) async =>
      _client.postJson('/security-lab/remediations', body: {'finding_id': findingId}, retry: false);

  Future<void> retest(String remediationId) async =>
      _client.postJson('/security-lab/remediations/${Uri.encodeComponent(remediationId)}/retest', retry: false);

  Future<void> finalize(String remediationId) async =>
      _client.postJson('/security-lab/remediations/${Uri.encodeComponent(remediationId)}/finalize', retry: false);
}

final securityLabRepositoryProvider = Provider<SecurityLabRepository>((ref) => SecurityLabRepository(ref.watch(apiClientProvider)));
final securityAccessProvider = FutureProvider.autoDispose<SecurityLabAccess>((ref) => ref.watch(securityLabRepositoryProvider).access());
final securityTargetsProvider = FutureProvider.autoDispose<List<SecurityTarget>>((ref) => ref.watch(securityLabRepositoryProvider).targets());
final securityScansProvider = FutureProvider.autoDispose<List<SecurityScan>>((ref) => ref.watch(securityLabRepositoryProvider).scans());
final securityFindingsProvider =
    FutureProvider.autoDispose.family<List<SecurityFinding>, String>((ref, id) => ref.watch(securityLabRepositoryProvider).findings(id));
final securityToolsProvider = FutureProvider.autoDispose<List<SecurityTool>>((ref) => ref.watch(securityLabRepositoryProvider).tools());
final securityRemediationsProvider = FutureProvider.autoDispose<List<SecurityRemediation>>(
  (ref) async {
    try {
      return await ref.watch(securityLabRepositoryProvider).remediations();
    } on Object {
      return const <SecurityRemediation>[];
    }
  },
);
final securityReportProvider =
    FutureProvider.autoDispose.family<SecurityReport, String>((ref, id) => ref.watch(securityLabRepositoryProvider).report(id));
