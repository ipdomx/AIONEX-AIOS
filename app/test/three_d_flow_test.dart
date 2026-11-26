import 'dart:typed_data';

import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/api/api_client.dart';
import 'package:aionex/src/core/api/api_exception.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/files/file_share.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:aionex/src/core/router/app_router.dart';
import 'package:aionex/src/core/security/device_security.dart';
import 'package:aionex/src/features/three_d/three_d_page.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

final png = Uint8List.fromList([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]);

Map<String, Object?> access({bool eligible = true, int remaining = 4}) => {
      'eligible': eligible,
      'plan_code': eligible ? 'professional' : 'free',
      'required_entitlement': 'three_d',
      'monthly_quota': 5,
      'monthly_used': 5 - remaining,
      'monthly_remaining': remaining,
      'active_jobs': 0,
      'max_concurrent_jobs': 1,
      'max_input_megabytes': 10,
      'max_texture_size': 2048,
      'compression_policy': 'compat',
      'signed_url_ttl_seconds': 900,
      'owner_managed': true,
      'service_enabled': true,
      'model_provider': 'triposr',
      'model_disclosure': {'provider': 'triposr', 'operator': 'IPDOMX', 'license': 'MIT', 'terms_version': 't1'},
      'third_party_terms_version': 't1',
      'third_party_terms_required': true,
    };

Map<String, Object?> job(String status) => {
      'id': 'j1',
      'project_id': 'p1',
      'status': status,
      'stage': status == 'completed' ? 'stored' : 'generating',
      'progress': status == 'completed' ? 100 : 40,
      'provider': 'triposr',
      'attempts': 1,
      'max_attempts': 3,
      'estimated_cost_usd': 0.02,
      'error_code': null,
      'error_message': null,
      'created_at': '2026-11-26T10:00:00Z',
      'has_artifact': status == 'completed',
      'artifact': status == 'completed' ? {'id': 'a1', 'filename': 'chair.glb'} : null,
    };

Future<ProviderContainer> start(WidgetTester tester, FakeAdapter adapter, List<DownloadedFile> shared) async {
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
      fileSharerProvider.overrideWithValue((file) async => shared.add(file)),
      sourceImagePickerProvider.overrideWithValue(() async => (bytes: png, name: 'chair.png')),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
  await tester.pumpAndSettle();
  container.read(routerProvider).go('/projects/p1/3d');
  await tester.pumpAndSettle();
  return container;
}

void main() {
  testWidgets('an image becomes a 3D job, is followed live and its GLB downloaded', (tester) async {
    var status = 'none';
    RequestOptions? created;
    final shared = <DownloadedFile>[];
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
        ('GET', '/auth/me') => jsonBody(200, userJson()),
        ('GET', '/projects/p1/3d/access') => jsonBody(200, access()),
        ('GET', '/projects/p1/3d/jobs') => jsonBody(200, status == 'none' ? <Object>[] : [job(status)]),
        ('POST', '/projects/p1/3d/jobs') => () {
            created = request;
            status = 'running';
            return jsonBody(202, job('queued'));
          }(),
        ('GET', '/projects/p1/3d/jobs/j1/artifact') => jsonBody(200, {
            'job_id': 'j1',
            'artifact_id': 'a1',
            'filename': 'chair.glb',
            'download_url': 'https://api.example.test/api/v1/projects/3d/artifacts/local?token=dl',
            'view_url': 'https://api.example.test/api/v1/projects/3d/artifacts/local?token=view',
            'exports': [
              {'format': 'usdz', 'filename': 'chair.usdz', 'url': 'https://api.example.test/api/v1/projects/3d/artifacts/local?token=usdz'},
            ],
            'expires_in': 900,
            'expires_at': '2026-11-26T10:15:00Z',
          }),
        ('GET', '/projects/3d/artifacts/local') => ResponseBody.fromString('glTF', 200, headers: {
            'content-type': ['model/gltf-binary'],
            'content-disposition': ['attachment; filename="chair.glb"'],
          }),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });
    await start(tester, adapter, shared);
    expect(find.text('No 3D jobs in this project yet.'), findsOneWidget);
    expect(find.text('Left this month: 4/5'), findsOneWidget);

    await tester.tap(find.byKey(const Key('three-d-pick')));
    await tester.pumpAndSettle();
    expect(find.text('Selected: chair.png'), findsOneWidget);
    await tester.tap(find.byKey(const Key('three-d-submit')));
    await tester.pumpAndSettle();
    // Terms first: nothing is sent without them.
    expect(created, isNull);
    expect(find.text('Accept the current third-party 3D model terms first.'), findsOneWidget);
    await tester.tap(find.byKey(const Key('three-d-terms')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('three-d-submit')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    final form = created!.data as FormData;
    final fields = {for (final f in form.fields) f.key: f.value};
    expect(fields['third_party_terms_accepted'], 'true');
    expect(fields['third_party_terms_version'], 't1');
    expect(form.files.single.key, 'image');
    expect(form.files.single.value.contentType.toString(), 'image/png');
    expect((created!.headers['Idempotency-Key'] as String).isNotEmpty, isTrue);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();

    status = 'completed';
    await tester.pump(const Duration(seconds: 4));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Completed'), findsOneWidget);
    await tester.tap(find.byKey(const Key('three-d-links-j1')));
    await tester.pumpAndSettle();
    expect(find.text('Download USDZ'), findsOneWidget);
    await tester.tap(find.byKey(const Key('three-d-glb-j1')));
    await tester.pumpAndSettle();
    expect(shared.single.filename, 'chair.glb');
    // Signed links carry their own token; no bearer header goes with them.
    final signed = adapter.requests.lastWhere((r) => r.uri.path.endsWith('/artifacts/local'));
    expect(signed.headers.containsKey('Authorization'), isFalse);
  });

  testWidgets('a plan without 3D sees the upgrade notice and cannot submit', (tester) async {
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
        ('GET', '/auth/me') => jsonBody(200, userJson()),
        ('GET', '/projects/p1/3d/access') => jsonBody(200, access(eligible: false)),
        ('GET', '/projects/p1/3d/jobs') => jsonBody(200, <Object>[]),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });
    await start(tester, adapter, []);
    expect(find.text('3D generation is not included in your plan'), findsOneWidget);
    expect(find.byKey(const Key('three-d-submit')), findsNothing);
  });

  test('signed downloads only follow links on the API host', () async {
    final store = MemorySessionStore();
    final client = fakeClient(FakeAdapter((r) async => jsonBody(200, {})), store);
    await expectLater(
      client.downloadSigned(Uri.parse('https://evil.example/x.glb'), fallbackName: 'x.glb'),
      throwsA(isA<ApiException>()),
    );
  });
}
