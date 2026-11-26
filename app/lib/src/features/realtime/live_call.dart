import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:livekit_client/livekit_client.dart' as lk;

import 'realtime_repository.dart';

/// One live media connection. The page only talks to this, so tests can
/// replace LiveKit with a fake.
abstract class LiveCall extends ChangeNotifier {
  bool get connected;
  bool get micEnabled;
  bool get cameraEnabled;
  bool get screenEnabled;
  int get remoteCount;

  Future<void> connect(RealtimeSession session, {required bool video});
  Future<void> setMic(bool on);
  Future<void> setCamera(bool on);
  Future<void> setScreen(bool on);
  Future<void> disconnect();

  /// The participants' video (or name tiles for audio only).
  Widget view(BuildContext context);
}

typedef LiveCallFactory = LiveCall Function();

final liveCallFactoryProvider = Provider<LiveCallFactory>((ref) => LiveKitCall.new);

class LiveKitCall extends LiveCall {
  lk.Room? _room;
  bool _mic = false;
  bool _camera = false;
  bool _screen = false;

  @override
  bool get connected => _room?.connectionState == lk.ConnectionState.connected;
  @override
  bool get micEnabled => _mic;
  @override
  bool get cameraEnabled => _camera;
  @override
  bool get screenEnabled => _screen;
  @override
  int get remoteCount => _room?.remoteParticipants.length ?? 0;

  @override
  Future<void> connect(RealtimeSession session, {required bool video}) async {
    final room = lk.Room(roomOptions: const lk.RoomOptions(adaptiveStream: true, dynacast: true));
    room.addListener(notifyListeners);
    _room = room;
    try {
      await room.connect(
        session.serverUrl,
        session.token,
        connectOptions: lk.ConnectOptions(
          rtcConfiguration: lk.RTCConfiguration(
            iceServers: [
              for (final s in session.iceServers)
                lk.RTCIceServer(urls: s.urls, username: s.username, credential: s.credential),
            ],
          ),
        ),
      );
      await setMic(true);
      if (video) await setCamera(true);
    } on Object {
      await disconnect();
      rethrow;
    }
  }

  @override
  Future<void> setMic(bool on) async {
    await _room?.localParticipant?.setMicrophoneEnabled(on);
    _mic = on;
    notifyListeners();
  }

  @override
  Future<void> setCamera(bool on) async {
    await _room?.localParticipant?.setCameraEnabled(on);
    _camera = on;
    notifyListeners();
  }

  @override
  Future<void> setScreen(bool on) async {
    await _room?.localParticipant?.setScreenShareEnabled(on);
    _screen = on;
    notifyListeners();
  }

  @override
  Future<void> disconnect() async {
    final room = _room;
    _room = null;
    _mic = _camera = _screen = false;
    if (room != null) {
      room.removeListener(notifyListeners);
      await room.disconnect();
      await room.dispose();
    }
    notifyListeners();
  }

  @override
  Widget view(BuildContext context) {
    final room = _room;
    if (room == null) return const SizedBox.shrink();
    final participants = <lk.Participant>[
      if (room.localParticipant != null) room.localParticipant!,
      ...room.remoteParticipants.values,
    ];
    return GridView.count(
      crossAxisCount: participants.length > 1 ? 2 : 1,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: 8,
      crossAxisSpacing: 8,
      childAspectRatio: 4 / 3,
      children: [for (final p in participants) _Tile(participant: p, local: p == room.localParticipant)],
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile({required this.participant, required this.local});

  final lk.Participant participant;
  final bool local;

  @override
  Widget build(BuildContext context) {
    final pubs = participant.videoTrackPublications.where((p) => p.track != null && !p.muted).toList();
    final screen = pubs.where((p) => p.source == lk.TrackSource.screenShareVideo);
    final track = (screen.isNotEmpty ? screen.first : (pubs.isNotEmpty ? pubs.first : null))?.track as lk.VideoTrack?;
    final name = participant.name.isNotEmpty ? participant.name : participant.identity;
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: ColoredBox(
        color: Colors.black,
        child: Stack(fit: StackFit.expand, children: [
          if (track != null)
            lk.VideoTrackRenderer(track, fit: lk.VideoViewFit.cover, mirrorMode: local ? lk.VideoViewMirrorMode.mirror : lk.VideoViewMirrorMode.off)
          else
            const Center(child: Icon(Icons.person, color: Colors.white54, size: 48)),
          PositionedDirectional(
            start: 8,
            bottom: 8,
            child: Row(children: [
              if (participant.isMuted) const Icon(Icons.mic_off, color: Colors.white, size: 16),
              const SizedBox(width: 4),
              Text(name, style: const TextStyle(color: Colors.white, fontSize: 12)),
            ]),
          ),
        ]),
      ),
    );
  }
}
