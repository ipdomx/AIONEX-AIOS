import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/providers.dart';
import '../workspace/workspace_models.dart' show newRequestId;

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;
DateTime? _d(Object? v) => v is String ? DateTime.tryParse(v) : null;
List<Map<String, Object?>> _rows(Object? v) =>
    v is List ? [for (final r in v) if (r is Map) r.cast<String, Object?>()] : const [];

/// A Facebook Page or Instagram Business account linked through Meta.
@immutable
class SocialAccount {
  const SocialAccount({
    required this.id,
    required this.provider,
    required this.displayName,
    required this.handle,
    required this.status,
    required this.healthState,
    required this.lastHealthAt,
  });

  final String id;
  final String provider;
  final String displayName;
  final String? handle;
  final String status;
  final String healthState;
  final DateTime? lastHealthAt;

  bool get usable => status == 'active' && healthState != 'revoked' && healthState != 'invalid' && healthState != 'expired';

  factory SocialAccount.fromJson(Map<String, Object?> j) => SocialAccount(
        id: _s(j['id']),
        provider: _s(j['provider']),
        displayName: _s(j['display_name']),
        handle: j['handle'] as String?,
        status: _s(j['status']),
        healthState: _s(j['health_state'], 'unknown'),
        lastHealthAt: _d(j['last_health_at']),
      );
}

@immutable
class SocialMedia {
  const SocialMedia({required this.ref, required this.source, required this.kind, required this.filename, required this.sizeBytes});
  final String ref;
  final String source;
  final String kind;
  final String filename;
  final int sizeBytes;

  factory SocialMedia.fromJson(Map<String, Object?> j) => SocialMedia(
        ref: _s(j['ref']),
        source: _s(j['source']),
        kind: _s(j['kind']),
        filename: _s(j['title'] ?? j['filename']),
        sizeBytes: _i(j['size_bytes']),
      );
}

@immutable
class SocialTarget {
  const SocialTarget({
    required this.accountName,
    required this.provider,
    required this.status,
    required this.attempts,
    required this.maxAttempts,
    required this.permalink,
    required this.errorCode,
    required this.errorMessage,
    this.id = '',
    this.remotePostId,
    this.publishedAt,
  });

  /// Target id: an ad can promote this published post (creative source "post").
  final String id;
  final String? remotePostId;
  final DateTime? publishedAt;
  final String accountName;
  final String provider;
  final String status;
  final int attempts;
  final int maxAttempts;
  final String? permalink;
  final String? errorCode;
  final String? errorMessage;

  factory SocialTarget.fromJson(Map<String, Object?> j) => SocialTarget(
        accountName: _s(j['account_name']),
        provider: _s(j['provider']),
        status: _s(j['status']),
        attempts: _i(j['attempts']),
        maxAttempts: _i(j['max_attempts']),
        permalink: j['permalink'] as String?,
        errorCode: j['error_code'] as String?,
        errorMessage: j['error_message'] as String?,
        id: _s(j['id']),
        remotePostId: j['remote_post_id'] as String?,
        publishedAt: _d(j['published_at']),
      );
}

@immutable
class SocialPost {
  const SocialPost({
    required this.id,
    required this.status,
    required this.postType,
    required this.caption,
    required this.scheduledAt,
    required this.timezone,
    required this.publishedAt,
    required this.createdAt,
    required this.targets,
  });

  final String id;
  final String status;
  final String postType;
  final String caption;
  final DateTime? scheduledAt;
  final String timezone;
  final DateTime? publishedAt;
  final DateTime? createdAt;
  final List<SocialTarget> targets;

  bool get isActive => status == 'scheduled' || status == 'publishing';
  bool get canCancel => status == 'scheduled' || status == 'publishing';
  bool get canDelete => status == 'draft' || status == 'canceled' || status == 'failed';
  bool get canPublish => status == 'draft';

  /// When the post went (or goes) out, for sorting the calendar list.
  DateTime? get when => publishedAt ?? scheduledAt;

  factory SocialPost.fromJson(Map<String, Object?> j) => SocialPost(
        id: _s(j['id']),
        status: _s(j['status']),
        postType: _s(j['post_type']),
        caption: _s(j['caption']),
        scheduledAt: _d(j['scheduled_at']),
        timezone: _s(j['timezone'], 'UTC'),
        publishedAt: _d(j['published_at']),
        createdAt: _d(j['created_at']),
        targets: [for (final t in _rows(j['targets'])) SocialTarget.fromJson(t)],
      );
}

@immutable
class SocialIssue {
  const SocialIssue({required this.code, required this.blocking, required this.provider});
  final String code;
  final bool blocking;
  final String provider;
}

/// The server's per-account check of a post before it is queued.
@immutable
class SocialValidation {
  const SocialValidation({required this.valid, required this.issues});
  final bool valid;
  final List<SocialIssue> issues;

  factory SocialValidation.fromJson(Map<String, Object?> j) => SocialValidation(
        valid: j['valid'] == true,
        issues: [
          for (final t in _rows(j['targets']))
            for (final i in _rows(t['issues']))
              SocialIssue(code: _s(i['code']), blocking: i['severity'] == 'error', provider: _s(t['provider'])),
        ],
      );
}

/// What the composer sends (the website's SocialPostInput).
@immutable
class SocialDraft {
  const SocialDraft({
    required this.postType,
    required this.caption,
    required this.accountIds,
    required this.media,
    required this.timezone,
    this.link,
  });

  final String postType;
  final String caption;
  final List<String> accountIds;
  final List<String> media;
  final String timezone;
  final String? link;

  Map<String, Object?> toJson({String? idempotencyKey}) => {
        'post_type': postType,
        'caption': caption,
        'link_url': (link == null || link!.trim().isEmpty) ? null : link!.trim(),
        'media': media,
        'account_ids': accountIds,
        'timezone': timezone,
        'client_idempotency_key': ?idempotencyKey,
      };
}

/// Social publishing, the same endpoints as vip-frontend/src/lib/api.ts.
class SocialRepository {
  SocialRepository(this._api);

  final ApiClient _api;

  String _post(String id) => '/social/posts/${Uri.encodeComponent(id)}';

  Future<List<SocialAccount>> accounts() async =>
      [for (final r in _rows((await _api.getJson('/social/accounts'))['items'])) SocialAccount.fromJson(r)];

  Future<SocialAccount> checkHealth(String id) async =>
      SocialAccount.fromJson(await _api.postJson('/social/accounts/${Uri.encodeComponent(id)}/health', retry: false));

  Future<void> disconnect(String id) async => _api.deleteJson('/social/accounts/${Uri.encodeComponent(id)}');

  Future<List<SocialPost>> posts() async =>
      [for (final r in _rows((await _api.getJson('/social/posts'))['items'])) SocialPost.fromJson(r)];

  Future<List<SocialMedia>> media() async {
    final json = await _api.getJson('/social/media');
    return [for (final r in [..._rows(json['uploads']), ..._rows(json['studio'])]) SocialMedia.fromJson(r)];
  }

  Future<SocialMedia> upload(List<int> bytes, {required String filename, required String mediaType}) async =>
      SocialMedia.fromJson(await _api.postMultipart(
        '/social/media',
        fields: const {},
        fileField: 'file',
        bytes: bytes,
        filename: filename,
        mediaType: mediaType,
      ));

  Future<SocialValidation> validate(SocialDraft draft) async =>
      SocialValidation.fromJson(await _api.postJson('/social/posts/validate', body: draft.toJson(), retry: false));

  /// One idempotency key per composed post, so a retried tap never makes two.
  Future<SocialPost> create(SocialDraft draft, {String? idempotencyKey}) async => SocialPost.fromJson(
        await _api.postJson('/social/posts', body: draft.toJson(idempotencyKey: idempotencyKey ?? newRequestId()), retry: false),
      );

  Future<SocialPost> publishNow(String id) async => SocialPost.fromJson(await _api.postJson('${_post(id)}/publish', retry: false));

  Future<SocialPost> schedule(String id, DateTime at, String timezone) async => SocialPost.fromJson(
        await _api.postJson('${_post(id)}/schedule', body: {'scheduled_at': at.toUtc().toIso8601String(), 'timezone': timezone}, retry: false),
      );

  Future<SocialPost> cancel(String id) async => SocialPost.fromJson(await _api.postJson('${_post(id)}/cancel', retry: false));

  Future<void> delete(String id) async => _api.deleteJson(_post(id));
}

final socialRepositoryProvider = Provider<SocialRepository>((ref) => SocialRepository(ref.watch(apiClientProvider)));

final socialAccountsProvider = FutureProvider.autoDispose<List<SocialAccount>>((ref) => ref.watch(socialRepositoryProvider).accounts());
final socialPostsProvider = FutureProvider.autoDispose<List<SocialPost>>((ref) => ref.watch(socialRepositoryProvider).posts());
final socialMediaProvider = FutureProvider.autoDispose<List<SocialMedia>>((ref) => ref.watch(socialRepositoryProvider).media());
