import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/auth/models.dart';
import '../../core/providers.dart';

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;
DateTime? _d(Object? v) => v is String ? DateTime.tryParse(v) : null;

/// What the signed-in user may do in the Academy (the website's academy-client rules).
@immutable
class AcademyAccess {
  const AcademyAccess({required this.paidPlan, required this.canRead, required this.canWrite, required this.canAssess});

  factory AcademyAccess.of(AppUser user) {
    final all = user.permissions.contains('*');
    return AcademyAccess(
      paidPlan: user.role != 'Free User' && user.organizationPlan.toLowerCase() != 'free',
      canRead: all || user.permissions.contains('academy:read'),
      canWrite: all || user.permissions.contains('academy:write'),
      canAssess: all || user.permissions.contains('academy:assess'),
    );
  }

  final bool paidPlan;
  final bool canRead;
  final bool canWrite;
  final bool canAssess;
}

@immutable
class AcademyCourse {
  const AcademyCourse({
    required this.id,
    required this.code,
    required this.title,
    required this.description,
    required this.passingScore,
    required this.version,
  });

  final String id;
  final String code;
  final String title;
  final String? description;
  final double passingScore;
  final int version;

  factory AcademyCourse.fromJson(Map<String, Object?> j) => AcademyCourse(
        id: _s(j['id']),
        code: _s(j['code']),
        title: _s(j['title']),
        description: j['description'] as String?,
        passingScore: j['passing_score'] is num ? (j['passing_score']! as num).toDouble() : 0,
        version: _i(j['version']),
      );
}

@immutable
class AcademyPackage {
  const AcademyPackage({
    required this.id,
    required this.courseId,
    required this.status,
    required this.version,
    required this.lessonCount,
    required this.downloadReady,
    required this.archiveSha256,
    required this.errorCode,
    required this.createdAt,
  });

  final String id;
  final String courseId;
  final String status;
  final int version;
  final int lessonCount;
  final bool downloadReady;
  final String? archiveSha256;
  final String? errorCode;
  final DateTime? createdAt;

  bool get isActive => status == 'queued' || status == 'building';
  bool get awaitsReview => status == 'review_pending';

  factory AcademyPackage.fromJson(Map<String, Object?> j) => AcademyPackage(
        id: _s(j['id']),
        courseId: _s(j['course_id']),
        status: _s(j['status']),
        version: _i(j['version']),
        lessonCount: _i(j['lesson_count']),
        downloadReady: j['download_ready'] == true,
        archiveSha256: j['archive_sha256'] as String?,
        errorCode: j['error_code'] as String?,
        createdAt: _d(j['created_at']),
      );
}

/// The Academy, the same endpoints as vip-frontend/src/lib/academy-api.ts.
class AcademyRepository {
  AcademyRepository(this._api);

  final ApiClient _api;

  static const locales = ['ar', 'en', 'fr', 'de', 'es', 'tr'];

  List<Map<String, Object?>> _rows(List<Object?> list) =>
      [for (final item in list) if (item is Map) item.cast<String, Object?>()];

  Future<List<AcademyCourse>> courses() async =>
      [for (final row in _rows(await _api.getList('/academy/courses', query: {'limit': 200}))) AcademyCourse.fromJson(row)];

  Future<List<AcademyPackage>> packages(String courseId) async => [
        for (final row in _rows(await _api.getList('/academy/courses/${Uri.encodeComponent(courseId)}/packages')))
          AcademyPackage.fromJson(row),
      ];

  Future<AcademyCourse> createCourse({
    required String code,
    required String title,
    required String description,
    required List<String> competencies,
    required double passingScore,
  }) async {
    final json = await _api.postJson(
      '/academy/courses',
      body: {
        'code': code.trim(),
        'title': title.trim(),
        'description': description.trim().isEmpty ? null : description.trim(),
        'competencies': competencies,
        'passing_score': passingScore,
      },
      retry: false,
    );
    return AcademyCourse.fromJson(json);
  }

  /// The idempotency key comes from the caller, so a retried tap never builds twice.
  Future<AcademyPackage> queuePackage(
    String courseId, {
    required String idempotencyKey,
    required String domain,
    required String audience,
    required int modules,
    required int lessonsPerModule,
  }) async {
    final json = await _api.postJson(
      '/academy/courses/${Uri.encodeComponent(courseId)}/packages',
      body: {
        'idempotency_key': idempotencyKey,
        'domain': domain.trim(),
        'audience': audience.trim(),
        'locales': locales,
        'module_count': modules,
        'lessons_per_module': lessonsPerModule,
        'citations': const <Object>[],
      },
      retry: false,
    );
    return AcademyPackage.fromJson(json);
  }

  Future<void> review(String packageId, {required bool approved, required String notes}) async {
    await _api.postJson(
      '/academy/packages/${Uri.encodeComponent(packageId)}/review',
      body: {'approved': approved, 'notes': notes.trim()},
      retry: false,
    );
  }

  Future<DownloadedFile> download(AcademyPackage package) => _api.download(
        '/academy/packages/${Uri.encodeComponent(package.id)}/download',
        fallbackName: 'course-${package.courseId}-v${package.version}.zip',
      );
}

final academyRepositoryProvider = Provider<AcademyRepository>((ref) => AcademyRepository(ref.watch(apiClientProvider)));

final academyCoursesProvider =
    FutureProvider.autoDispose<List<AcademyCourse>>((ref) => ref.watch(academyRepositoryProvider).courses());

final academyPackagesProvider = FutureProvider.autoDispose.family<List<AcademyPackage>, String>(
  (ref, courseId) => ref.watch(academyRepositoryProvider).packages(courseId),
);
