import 'dart:convert';

import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:aionex/src/core/router/app_router.dart';
import 'package:aionex/src/core/security/device_security.dart';
import 'package:aionex/src/features/realtime/live_call.dart';
import 'package:aionex/src/features/realtime/realtime_repository.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

Object? body(RequestOptions request) => request.data is String ? jsonDecode(request.data as String) : request.data;

class FakeCall extends LiveCall {
  RealtimeSession? session;
  bool video = false;
  bool _connected = false;
  bool _mic = false;
  bool _camera = false;
  bool _screen = false;
  @override
  bool get connected => _connected;
  @override
  bool get micEnabled => _mic;
  @override
  bool get cameraEnabled => _camera;
  @override
  bool get screenEnabled => _screen;
  @override
  int get remoteCount => 0;
  @override
  Future<void> connect(RealtimeSession s, {required bool video}) async {
    session = s;
    this.video = video;
    _connected = true;
    _mic = true;
    _camera = video;
    notifyListeners();
  }

  @override
  Future<void> setMic(bool on) async {
    _mic = on;
    notifyListeners();
  }

  @override
  Future<void> setCamera(bool on) async {
    _camera = on;
    notifyListeners();
  }

  @override
  Future<void> setScreen(bool on) async {
    _screen = on;
    notifyListeners();
  }

  @override
  Future<void> disconnect() async {
    _connected = false;
    notifyListeners();
  }

  @override
  Widget view(BuildContext context) => Text(_connected ? 'live media' : 'offline');
}

Map<String, Object?> room({int count = 0}) => {
      'id': 'r1',
      'room_key': 'Team sync',
      'status': 'open',
      'media_mode': 'audio_video',
      'participant_count': count,
      'max_participants': 50,
      'allow_screen_share': true,
      'created_by_id': 'u1',
    };

Future<ProviderContainer> start(WidgetTester tester, FakeAdapter adapter, List<FakeCall> calls) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final store = MemorySessionStore(refreshToken: 'saved');
  final container = ProviderContainer(
    retry: retryOnlyNetworkErrors,
    overrides: [
      sharedPreferencesProvider.overrideWithValue(preferences),
      sessionStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(fakeClient(adapter, store)),
      deviceIntegrityProvider.overrideWith((ref) async => DeviceIntegrity.unknown),
      liveCallFactoryProvider.overrideWithValue(() {
        final call = FakeCall();
        calls.add(call);
        return call;
      }),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
  await tester.pumpAndSettle();
  container.read(routerProvider).go('/realtime');
  await tester.pumpAndSettle();
  return container;
}

void main() {
  testWidgets('a room is created, joined with short-lived credentials, recorded with consent and left', (tester) async {
    final user = userJson(role: 'Member', plan: 'professional');
    var rooms = <Object>[];
    var recordings = <Object>[];
    final sent = <String, Object?>{};
    final calls = <FakeCall>[];
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, {...grantJson(), 'user': user}),
        ('GET', '/auth/me') => jsonBody(200, user),
        ('GET', '/realtime/media/readiness') => jsonBody(200, {'enabled': true, 'provider': 'livekit'}),
        ('GET', '/realtime/media/rooms') => jsonBody(200, rooms),
        ('POST', '/realtime/media/rooms') => () {
            sent['create'] = body(request);
            rooms = [room()];
            return jsonBody(201, room());
          }(),
        ('POST', '/realtime/media/rooms/r1/join') => () {
            sent['join'] = body(request);
            rooms = [room(count: 1)];
            return jsonBody(200, {
              'room': room(count: 1),
              'participant_id': 'pa1',
              'session': {
                'token': 'short-lived',
                'expires_at': '2026-11-26T10:10:00Z',
                'server_url': 'wss://api.example.test/livekit',
                'ice_servers': [
                  {'urls': ['turn:203.0.113.5:443?transport=tcp'], 'username': 'u', 'credential': 'c'},
                ],
                'provider': 'livekit',
              },
              'admission_grant_returned': false,
            });
          }(),
        ('GET', '/realtime/media/rooms/r1/recordings') => jsonBody(200, recordings),
        ('POST', '/realtime/media/rooms/r1/recordings') => () {
            sent['recording'] = body(request);
            recordings = [
              {'id': 'rec1', 'title': 'Team sync recording', 'status': 'awaiting_consent', 'required_consent_count': 1, 'consented_count': 0},
            ];
            return jsonBody(201, recordings.first);
          }(),
        ('POST', '/realtime/media/recordings/rec1/consent') => () {
            sent['consent'] = body(request);
            recordings = [
              {'id': 'rec1', 'title': 'Team sync recording', 'status': 'active', 'required_consent_count': 1, 'consented_count': 1},
            ];
            return jsonBody(200, recordings.first);
          }(),
        ('POST', '/realtime/media/rooms/r1/leave') => () {
            sent['leave'] = true;
            rooms = [room()];
            return jsonBody(200, {'room_id': 'r1', 'left': true});
          }(),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });
    await start(tester, adapter, calls);
    expect(find.text('Live media runtime is online and ready.'), findsOneWidget);
    expect(find.text('No realtime rooms yet.'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('room-key')), 'Team sync');
    await tester.tap(find.byKey(const Key('create-room')));
    await tester.pumpAndSettle();
    expect((sent['create']! as Map)['media_mode'], 'audio_video');
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('join-r1')));
    await tester.pumpAndSettle();
    final call = calls.single;
    expect(call.session!.token, 'short-lived');
    expect(call.session!.serverUrl, 'wss://api.example.test/livekit');
    expect(call.session!.iceServers.single.username, 'u');
    expect(call.video, isTrue);
    expect(find.text('live media'), findsOneWidget);
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('toggle-mic')));
    await tester.pumpAndSettle();
    expect(call.micEnabled, isFalse);

    await tester.tap(find.byKey(const Key('request-recording')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('recording-confirm')));
    await tester.pumpAndSettle();
    expect((sent['recording']! as Map)['consent_version'], 'realtime-recording-v1');
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('agree-rec1')));
    await tester.pumpAndSettle();
    expect(sent['consent'], {'consented': true});
    expect(find.byKey(const Key('stop-rec1')), findsOneWidget);
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.byKey(const Key('leave-room')));
    await tester.tap(find.byKey(const Key('leave-room')));
    await tester.pumpAndSettle();
    expect(call.connected, isFalse);
    expect(sent['leave'], isTrue);
    expect(find.text('live media'), findsNothing);
  });

  testWidgets('the free plan sees the paid-plan notice and never asks for rooms', (tester) async {
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
        ('GET', '/auth/me') => jsonBody(200, userJson()),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });
    await start(tester, adapter, []);
    expect(find.text('Live rooms need a paid plan'), findsOneWidget);
    expect(adapter.paths.where((p) => p.contains('/realtime')), isEmpty);
  });
}
