import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/providers.dart';
import '../workspace/workspace_models.dart' show newRequestId;

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;

@immutable
class RealtimeReadiness {
  const RealtimeReadiness({required this.enabled, required this.provider});
  final bool enabled;
  final String provider;

  factory RealtimeReadiness.fromJson(Map<String, Object?> j) =>
      RealtimeReadiness(enabled: j['enabled'] == true, provider: _s(j['provider']));
}

@immutable
class RealtimeRoom {
  const RealtimeRoom({
    required this.id,
    required this.roomKey,
    required this.status,
    required this.mediaMode,
    required this.participantCount,
    required this.maxParticipants,
    required this.allowScreenShare,
    required this.createdById,
  });

  final String id;
  final String roomKey;
  final String status;
  final String mediaMode;
  final int participantCount;
  final int maxParticipants;
  final bool allowScreenShare;
  final String createdById;

  bool get isOpen => status != 'closed';

  factory RealtimeRoom.fromJson(Map<String, Object?> j) => RealtimeRoom(
        id: _s(j['id']),
        roomKey: _s(j['room_key']),
        status: _s(j['status']),
        mediaMode: _s(j['media_mode']),
        participantCount: _i(j['participant_count']),
        maxParticipants: _i(j['max_participants']),
        allowScreenShare: j['allow_screen_share'] == true,
        createdById: _s(j['created_by_id']),
      );
}

/// A TURN/STUN server as the API hands it out (short-lived credentials).
@immutable
class IceServer {
  const IceServer({required this.urls, this.username, this.credential});
  final List<String> urls;
  final String? username;
  final String? credential;

  factory IceServer.fromJson(Map<String, Object?> j) {
    final urls = j['urls'];
    return IceServer(
      urls: urls is String ? [urls] : (urls is List ? urls.whereType<String>().toList() : const []),
      username: j['username'] as String?,
      credential: j['credential'] as String?,
    );
  }
}

/// What joining returns: the LiveKit address and a short-lived participant token.
@immutable
class RealtimeSession {
  const RealtimeSession({required this.serverUrl, required this.token, required this.iceServers});
  final String serverUrl;
  final String token;
  final List<IceServer> iceServers;
}

@immutable
class RealtimeRecording {
  const RealtimeRecording({
    required this.id,
    required this.title,
    required this.status,
    required this.requiredConsents,
    required this.consented,
    required this.studioAssetId,
  });

  final String id;
  final String title;
  final String status;
  final int requiredConsents;
  final int consented;
  final String? studioAssetId;

  static const activeStatuses = {'awaiting_consent', 'starting', 'active', 'ending'};
  bool get isActive => activeStatuses.contains(status);

  factory RealtimeRecording.fromJson(Map<String, Object?> j) => RealtimeRecording(
        id: _s(j['id']),
        title: _s(j['title']),
        status: _s(j['status']),
        requiredConsents: _i(j['required_consent_count']),
        consented: _i(j['consented_count']),
        studioAssetId: j['studio_asset_id'] as String?,
      );
}

/// Realtime rooms, the same endpoints as vip-frontend/src/lib/realtime-api.ts.
class RealtimeRepository {
  RealtimeRepository(this._api);

  final ApiClient _api;

  static const consentVersion = 'realtime-recording-v1';

  List<Map<String, Object?>> _rows(List<Object?> list) =>
      [for (final item in list) if (item is Map) item.cast<String, Object?>()];

  String _room(String id) => '/realtime/media/rooms/${Uri.encodeComponent(id)}';

  Future<RealtimeReadiness> readiness() async =>
      RealtimeReadiness.fromJson(await _api.getJson('/realtime/media/readiness'));

  Future<List<RealtimeRoom>> rooms() async => [
        for (final row in _rows(await _api.getList('/realtime/media/rooms', query: {'limit': 100})))
          RealtimeRoom.fromJson(row),
      ];

  Future<RealtimeRoom> create(String roomKey, {bool video = true}) async => RealtimeRoom.fromJson(
        await _api.postJson('/realtime/media/rooms', body: {
          'room_key': roomKey.trim(),
          'idempotency_key': newRequestId(),
          'room_type': 'meeting',
          'media_mode': video ? 'audio_video' : 'audio',
          'max_participants': 50,
          'allow_screen_share': true,
        }, retry: false),
      );

  Future<RealtimeSession> join(RealtimeRoom room) async {
    final json = await _api.postJson('${_room(room.id)}/join', body: {
      'idempotency_key': newRequestId(),
      'can_publish': true,
      'can_subscribe': true,
      'can_screen_share': room.allowScreenShare,
    }, retry: false);
    final session = json['session'] is Map ? (json['session']! as Map).cast<String, Object?>() : const <String, Object?>{};
    return RealtimeSession(
      serverUrl: _s(session['server_url']),
      token: _s(session['token']),
      iceServers: [
        if (session['ice_servers'] is List)
          for (final s in (session['ice_servers']! as List).whereType<Map<Object?, Object?>>())
            IceServer.fromJson(s.cast<String, Object?>()),
      ],
    );
  }

  Future<void> leave(String roomId) async => _api.postJson('${_room(roomId)}/leave', retry: false);

  Future<void> close(String roomId) async => _api.postJson('${_room(roomId)}/close', retry: false);

  Future<List<RealtimeRecording>> recordings(String roomId) async => [
        for (final row in _rows(await _api.getList('${_room(roomId)}/recordings')))
          RealtimeRecording.fromJson(row),
      ];

  Future<void> requestRecording(String roomId, String title) async => _api.postJson('${_room(roomId)}/recordings', body: {
        'title': title.trim(),
        'idempotency_key': newRequestId(),
        'consent_version': consentVersion,
        'retention_days': 30,
      }, retry: false);

  Future<void> consent(String recordingId, bool consented) async => _api.postJson(
        '/realtime/media/recordings/${Uri.encodeComponent(recordingId)}/consent',
        body: {'consented': consented},
        retry: false,
      );

  Future<void> stopRecording(String recordingId) async =>
      _api.postJson('/realtime/media/recordings/${Uri.encodeComponent(recordingId)}/stop', retry: false);
}

final realtimeRepositoryProvider = Provider<RealtimeRepository>((ref) => RealtimeRepository(ref.watch(apiClientProvider)));

final realtimeReadinessProvider =
    FutureProvider.autoDispose<RealtimeReadiness>((ref) => ref.watch(realtimeRepositoryProvider).readiness());

final realtimeRoomsProvider =
    FutureProvider.autoDispose<List<RealtimeRoom>>((ref) => ref.watch(realtimeRepositoryProvider).rooms());

final realtimeRecordingsProvider = FutureProvider.autoDispose.family<List<RealtimeRecording>, String>(
  (ref, roomId) => ref.watch(realtimeRepositoryProvider).recordings(roomId),
);
