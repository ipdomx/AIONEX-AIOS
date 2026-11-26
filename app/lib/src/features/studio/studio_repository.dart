import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/providers.dart';

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;
DateTime? _d(Object? v) => v is String ? DateTime.tryParse(v) : null;

@immutable
class StudioDepartment {
  const StudioDepartment({required this.id, required this.name, required this.assetType, required this.outputs});
  final String id;
  final String name;
  final String assetType;
  final List<String> outputs;

  /// Code and website jobs take a programming language (the website shows the field for these).
  bool get takesProgrammingLanguage => id == 'code' || id == 'website' || id == 'three-d';

  factory StudioDepartment.fromJson(Map<String, Object?> j) => StudioDepartment(
        id: _s(j['id']),
        name: _s(j['name']),
        assetType: _s(j['asset_type']),
        outputs: j['outputs'] is List ? (j['outputs']! as List).whereType<String>().toList() : const [],
      );
}

@immutable
class StudioJob {
  const StudioJob({
    required this.id,
    required this.department,
    required this.title,
    required this.status,
    required this.progress,
    required this.safetyStatus,
    required this.provider,
    required this.errorMessage,
    required this.attempts,
    required this.maxAttempts,
    required this.costUsd,
    required this.createdAt,
  });

  final String id;
  final String department;
  final String title;
  final String status;
  final int progress;
  final String safetyStatus;
  final String? provider;
  final String? errorMessage;
  final int attempts;
  final int maxAttempts;
  final double? costUsd;
  final DateTime? createdAt;

  // Same rules as the website's studio-client.tsx.
  bool get isActive => !const {'completed', 'blocked', 'failed', 'cancelled'}.contains(status);
  bool get canRetry => status == 'failed' || status == 'cancelled';
  bool get canCancel => status == 'queued' || status == 'running';

  factory StudioJob.fromJson(Map<String, Object?> j) {
    final result = j['result_metadata'];
    final request = j['request_metadata'];
    final cost = (result is Map ? result['external_cost_usd'] : null) ?? (request is Map ? request['external_cost_usd'] : null);
    return StudioJob(
      id: _s(j['id']),
      department: _s(j['department']),
      title: _s(j['title']),
      status: _s(j['status']),
      progress: _i(j['progress']),
      safetyStatus: _s(j['safety_status']),
      provider: j['provider'] as String?,
      errorMessage: j['error_message'] as String?,
      attempts: _i(j['attempts']),
      maxAttempts: _i(j['max_attempts']),
      costUsd: cost is num ? cost.toDouble() : null,
      createdAt: _d(j['created_at']),
    );
  }
}

@immutable
class StudioAsset {
  const StudioAsset({
    required this.id,
    required this.department,
    required this.title,
    required this.filename,
    required this.mediaType,
    required this.sizeBytes,
    required this.currentRevision,
    required this.attachedProjectIds,
    required this.updatedAt,
  });

  final String id;
  final String department;
  final String title;
  final String filename;
  final String mediaType;
  final int sizeBytes;
  final int currentRevision;
  final List<String> attachedProjectIds;
  final DateTime? updatedAt;

  factory StudioAsset.fromJson(Map<String, Object?> j) => StudioAsset(
        id: _s(j['id']),
        department: _s(j['department']),
        title: _s(j['title']),
        filename: _s(j['filename']),
        mediaType: _s(j['media_type']),
        sizeBytes: _i(j['size_bytes']),
        currentRevision: _i(j['current_revision']),
        attachedProjectIds:
            j['attached_project_ids'] is List ? (j['attached_project_ids']! as List).whereType<String>().toList() : const [],
        updatedAt: _d(j['updated_at']),
      );
}

@immutable
class StudioRevision {
  const StudioRevision({required this.number, required this.filename, required this.changeNote, required this.createdAt});
  final int number;
  final String filename;
  final String? changeNote;
  final DateTime? createdAt;

  factory StudioRevision.fromJson(Map<String, Object?> j) => StudioRevision(
        number: _i(j['revision_number']),
        filename: _s(j['filename']),
        changeNote: j['change_note'] as String?,
        createdAt: _d(j['created_at']),
      );
}

/// The Production Studio (/studio), the same endpoints as vip-frontend/src/lib/studio-api.ts.
class StudioRepository {
  StudioRepository(this._api);

  final ApiClient _api;

  List<Map<String, Object?>> _rows(List<Object?> list) =>
      [for (final item in list) if (item is Map) item.cast<String, Object?>()];

  Future<List<StudioDepartment>> departments() async {
    final json = await _api.getJson('/studio/departments');
    final list = json['departments'];
    return list is List ? [for (final row in _rows(list)) StudioDepartment.fromJson(row)] : const [];
  }

  Future<List<StudioJob>> jobs() async =>
      [for (final row in _rows(await _api.getList('/studio/jobs', query: {'limit': 100}))) StudioJob.fromJson(row)];

  Future<List<StudioAsset>> assets() async =>
      [for (final row in _rows(await _api.getList('/studio/assets', query: {'limit': 100}))) StudioAsset.fromJson(row)];

  Future<StudioJob> createJob({
    required String department,
    required String title,
    required String brief,
    required String language,
    required String style,
    String? target,
    String? programmingLanguage,
    String? projectId,
  }) async {
    final json = await _api.postJson(
      '/studio/jobs',
      body: {
        'department': department,
        'title': title.trim(),
        'brief': brief.trim(),
        'language': language,
        'style': style.trim().isEmpty ? 'professional' : style.trim(),
        'target': (target?.trim().isEmpty ?? true) ? null : target!.trim(),
        'programming_language': (programmingLanguage?.trim().isEmpty ?? true) ? null : programmingLanguage!.trim(),
        'project_id': projectId,
      },
      retry: false,
    );
    return StudioJob.fromJson(json);
  }

  Future<void> retry(String jobId) async =>
      _api.postJson('/studio/jobs/${Uri.encodeComponent(jobId)}/retry', retry: false);

  Future<void> cancel(String jobId) async =>
      _api.postJson('/studio/jobs/${Uri.encodeComponent(jobId)}/cancel', retry: false);

  Future<List<StudioRevision>> revisions(String assetId) async => [
        for (final row in _rows(await _api.getList('/studio/assets/${Uri.encodeComponent(assetId)}/revisions')))
          StudioRevision.fromJson(row),
      ];

  Future<void> createRevision(String assetId, {required String brief, required String changeNote}) async {
    await _api.postJson(
      '/studio/assets/${Uri.encodeComponent(assetId)}/revisions',
      body: {'brief': brief.trim(), 'change_note': changeNote.trim()},
      retry: false,
    );
  }

  Future<void> attach(String assetId, String projectId) async {
    await _api.postJson('/studio/assets/${Uri.encodeComponent(assetId)}/attach', body: {'project_id': projectId}, retry: false);
  }

  Future<DownloadedFile> download(StudioAsset asset) =>
      _api.download('/studio/assets/${Uri.encodeComponent(asset.id)}/download', fallbackName: asset.filename);
}

final studioRepositoryProvider = Provider<StudioRepository>((ref) => StudioRepository(ref.watch(apiClientProvider)));

final studioDepartmentsProvider =
    FutureProvider.autoDispose<List<StudioDepartment>>((ref) => ref.watch(studioRepositoryProvider).departments());
final studioJobsProvider = FutureProvider.autoDispose<List<StudioJob>>((ref) => ref.watch(studioRepositoryProvider).jobs());
final studioAssetsProvider =
    FutureProvider.autoDispose<List<StudioAsset>>((ref) => ref.watch(studioRepositoryProvider).assets());
