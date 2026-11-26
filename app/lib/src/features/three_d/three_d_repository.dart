import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/providers.dart';
import '../workspace/workspace_models.dart' show newRequestId;

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;
double _n(Object? v) => v is num ? v.toDouble() : 0;
DateTime? _d(Object? v) => v is String ? DateTime.tryParse(v) : null;

/// What the server allows this account to do (GET /projects/{id}/3d/access).
@immutable
class ThreeDAccess {
  const ThreeDAccess({
    required this.eligible,
    required this.serviceEnabled,
    required this.planCode,
    required this.monthlyQuota,
    required this.monthlyRemaining,
    required this.activeJobs,
    required this.maxConcurrentJobs,
    required this.maxInputMegabytes,
    required this.maxTextureSize,
    required this.provider,
    required this.operator,
    required this.license,
    
    required this.termsVersion,
    required this.termsRequired,
    required this.signedUrlTtlSeconds,
  });

  final bool eligible;
  final bool serviceEnabled;
  final String planCode;
  final int monthlyQuota;
  final int monthlyRemaining;
  final int activeJobs;
  final int maxConcurrentJobs;
  final int maxInputMegabytes;
  final int maxTextureSize;
  final String provider;
  final String operator;
  final String license;
  final String termsVersion;
  final bool termsRequired;
  final int signedUrlTtlSeconds;

  /// Hunyuan3D output carries a no-affiliation notice, as on the website.
  bool get showsHunyuanNotice => provider == 'hunyuan3d';

  bool get canCreate => eligible && serviceEnabled && monthlyRemaining > 0 && activeJobs < maxConcurrentJobs;

  factory ThreeDAccess.fromJson(Map<String, Object?> j) {
    final disclosure = j['model_disclosure'] is Map ? (j['model_disclosure']! as Map).cast<String, Object?>() : const <String, Object?>{};
    return ThreeDAccess(
      eligible: j['eligible'] == true,
      serviceEnabled: j['service_enabled'] != false,
      planCode: _s(j['plan_code']),
      monthlyQuota: _i(j['monthly_quota']),
      monthlyRemaining: _i(j['monthly_remaining']),
      activeJobs: _i(j['active_jobs']),
      maxConcurrentJobs: _i(j['max_concurrent_jobs']),
      maxInputMegabytes: _i(j['max_input_megabytes']),
      maxTextureSize: _i(j['max_texture_size']),
      provider: _s(j['model_provider']),
      operator: _s(disclosure['operator']),
      license: _s(disclosure['license']),
      termsVersion: _s(j['third_party_terms_version']),
      termsRequired: j['third_party_terms_required'] == true,
      signedUrlTtlSeconds: _i(j['signed_url_ttl_seconds']),
    );
  }
}

@immutable
class ThreeDJob {
  const ThreeDJob({
    required this.id,
    required this.status,
    required this.stage,
    required this.progress,
    required this.attempts,
    required this.maxAttempts,
    required this.estimatedCostUsd,
    required this.errorMessage,
    required this.hasArtifact,
    required this.artifactFilename,
    required this.createdAt,
  });

  final String id;
  final String status;
  final String stage;
  final int progress;
  final int attempts;
  final int maxAttempts;
  final double estimatedCostUsd;
  final String? errorMessage;
  final bool hasArtifact;
  final String? artifactFilename;
  final DateTime? createdAt;

  bool get isActive => status == 'queued' || status == 'running' || status == 'cancel_requested';
  bool get canCancel => status == 'queued' || status == 'running';

  factory ThreeDJob.fromJson(Map<String, Object?> j) {
    final artifact = j['artifact'] is Map ? (j['artifact']! as Map).cast<String, Object?>() : null;
    return ThreeDJob(
      id: _s(j['id']),
      status: _s(j['status']),
      stage: _s(j['stage']),
      progress: _i(j['progress']),
      attempts: _i(j['attempts']),
      maxAttempts: _i(j['max_attempts']),
      estimatedCostUsd: _n(j['estimated_cost_usd']),
      errorMessage: j['error_message'] as String?,
      hasArtifact: j['has_artifact'] == true,
      artifactFilename: artifact?['filename'] as String?,
      createdAt: _d(j['created_at']),
    );
  }
}

@immutable
class ThreeDLink {
  const ThreeDLink({required this.label, required this.filename, required this.url});
  final String label;
  final String filename;
  final Uri url;
}

/// Signed, short-lived links for one finished job.
@immutable
class ThreeDLinks {
  const ThreeDLinks({required this.glb, required this.exports, required this.previewUrl, required this.expiresAt});
  final ThreeDLink glb;
  final List<ThreeDLink> exports;
  final Uri? previewUrl;
  final DateTime? expiresAt;

  factory ThreeDLinks.fromJson(Map<String, Object?> j) {
    final filename = _s(j['filename'], 'model.glb');
    return ThreeDLinks(
      glb: ThreeDLink(label: 'glb', filename: filename, url: Uri.parse(_s(j['download_url']))),
      exports: [
        if (j['exports'] is List)
          for (final e in (j['exports']! as List).whereType<Map<Object?, Object?>>())
            ThreeDLink(label: _s(e['format']), filename: _s(e['filename']), url: Uri.parse(_s(e['url']))),
      ],
      previewUrl: j['preview_url'] is String ? Uri.tryParse(j['preview_url']! as String) : null,
      expiresAt: _d(j['expires_at']),
    );
  }
}

/// Image-to-3D inside a project, the same endpoints as vip-frontend's three-d-client.
class ThreeDRepository {
  ThreeDRepository(this._api);

  final ApiClient _api;

  String _base(String projectId) => '/projects/${Uri.encodeComponent(projectId)}/3d';

  Future<ThreeDAccess> access(String projectId) async => ThreeDAccess.fromJson(await _api.getJson('${_base(projectId)}/access'));

  Future<List<ThreeDJob>> jobs(String projectId) async => [
        for (final row in await _api.getList('${_base(projectId)}/jobs', query: {'limit': 20}))
          if (row is Map) ThreeDJob.fromJson(row.cast<String, Object?>()),
      ];

  /// [idempotencyKey] stays the same for retries of one submission.
  Future<ThreeDJob> create(
    String projectId, {
    required List<int> image,
    required String filename,
    required String mediaType,
    required String termsVersion,
    required bool termsAccepted,
    int? textureSize,
    String? idempotencyKey,
  }) async {
    final json = await _api.postMultipart(
      '${_base(projectId)}/jobs',
      fields: {
        'seed': '12345',
        if (textureSize != null) 'texture_size': '$textureSize',
        'third_party_terms_accepted': '$termsAccepted',
        'third_party_terms_version': termsVersion,
      },
      fileField: 'image',
      bytes: image,
      filename: filename,
      mediaType: mediaType,
      headers: {'Idempotency-Key': idempotencyKey ?? newRequestId()},
    );
    return ThreeDJob.fromJson(json);
  }

  Future<void> cancel(String projectId, String jobId) async =>
      _api.postJson('${_base(projectId)}/jobs/${Uri.encodeComponent(jobId)}/cancel', retry: false);

  Future<ThreeDJob> clarify(
    String projectId,
    String jobId, {
    required List<int> image,
    required String filename,
    required String mediaType,
    required String termsVersion,
    required bool termsAccepted,
  }) async {
    final json = await _api.postMultipart(
      '${_base(projectId)}/jobs/${Uri.encodeComponent(jobId)}/clarify',
      fields: {'third_party_terms_accepted': '$termsAccepted', 'third_party_terms_version': termsVersion},
      fileField: 'image',
      bytes: image,
      filename: filename,
      mediaType: mediaType,
    );
    return ThreeDJob.fromJson(json);
  }

  Future<ThreeDLinks> links(String projectId, String jobId) async =>
      ThreeDLinks.fromJson(await _api.getJson('${_base(projectId)}/jobs/${Uri.encodeComponent(jobId)}/artifact'));

  Future<DownloadedFile> download(ThreeDLink link) => _api.downloadSigned(link.url, fallbackName: link.filename);
}

/// PNG, JPEG or WebP by their magic bytes, like the server checks.
String? sourceImageType(List<int> b) {
  if (b.length > 8 && b[0] == 0x89 && b[1] == 0x50 && b[2] == 0x4e && b[3] == 0x47) return 'image/png';
  if (b.length > 3 && b[0] == 0xff && b[1] == 0xd8) return 'image/jpeg';
  if (b.length > 12 && b[0] == 0x52 && b[1] == 0x49 && b[2] == 0x46 && b[3] == 0x46 && b[8] == 0x57 && b[9] == 0x45 && b[10] == 0x42 && b[11] == 0x50) {
    return 'image/webp';
  }
  return null;
}

final threeDRepositoryProvider = Provider<ThreeDRepository>((ref) => ThreeDRepository(ref.watch(apiClientProvider)));

final threeDAccessProvider =
    FutureProvider.autoDispose.family<ThreeDAccess, String>((ref, projectId) => ref.watch(threeDRepositoryProvider).access(projectId));

final threeDJobsProvider =
    FutureProvider.autoDispose.family<List<ThreeDJob>, String>((ref, projectId) => ref.watch(threeDRepositoryProvider).jobs(projectId));
