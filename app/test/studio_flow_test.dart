import 'dart:convert';

import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/api/api_client.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/files/file_share.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:aionex/src/core/router/app_router.dart';
import 'package:aionex/src/core/security/device_security.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

Object? body(RequestOptions request) => request.data is String ? jsonDecode(request.data as String) : request.data;

Map<String, Object?> job(String status, {int progress = 0}) => {
      'id': 'j1',
      'project_id': null,
      'revision_of_asset_id': null,
      'department': 'text',
      'output_kind': 'manuscript',
      'title': 'Launch brief',
      'brief': 'A brief for the launch campaign.',
      'language': 'en',
      'style': 'professional',
      'target': null,
      'programming_language': null,
      'change_note': null,
      'provider_mode': 'local',
      'provider': null,
      'model': null,
      'status': status,
      'progress': progress,
      'safety_status': 'passed',
      'safety_findings': <Object>[],
      'request_metadata': <String, Object?>{},
      'result_metadata': <String, Object?>{},
      'error_code': null,
      'error_message': null,
      'attempts': 1,
      'max_attempts': 3,
      'created_at': '2026-11-26T10:00:00Z',
      'updated_at': '2026-11-26T10:00:00Z',
    };

void main() {
  testWidgets('a studio job is queued, followed live and its asset downloaded', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.6;
    addTearDown(tester.view.reset);
    var status = 'none';
    Object? created;
    final shared = <DownloadedFile>[];
    SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
    final preferences = await SharedPreferences.getInstance();
    final store = MemorySessionStore(refreshToken: 'saved');
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
        ('GET', '/auth/me') => jsonBody(200, userJson()),
        ('GET', '/studio/departments') => jsonBody(200, {
            'departments': [
              {'id': 'text', 'name': 'Text Studio', 'asset_type': 'text', 'outputs': ['manuscript', 'outline']},
              {'id': 'code', 'name': 'Code Studio', 'asset_type': 'code', 'outputs': ['source']},
            ],
            'count': 2,
            'provider_mode': 'local',
            'provider_activation_batch': 'x',
          }),
        ('GET', '/studio/jobs') => jsonBody(200, status == 'none' ? <Object>[] : [job(status, progress: 40)]),
        ('POST', '/studio/jobs') => () {
            created = body(request);
            status = 'running';
            return jsonBody(201, job('queued'));
          }(),
        ('GET', '/studio/assets') => jsonBody(200, status == 'completed'
            ? [
                {
                  'id': 'a1',
                  'job_id': 'j1',
                  'project_id': null,
                  'department': 'text',
                  'asset_type': 'text',
                  'title': 'Launch brief',
                  'filename': 'launch-brief.md',
                  'media_type': 'text/markdown',
                  'checksum': 'x',
                  'size_bytes': 2048,
                  'status': 'active',
                  'current_revision': 1,
                  'metadata': <String, Object?>{},
                  'attached_project_ids': <String>[],
                  'created_at': '2026-11-26T10:01:00Z',
                  'updated_at': '2026-11-26T10:01:00Z',
                },
              ]
            : <Object>[]),
        ('GET', '/studio/assets/a1/download') => ResponseBody.fromString('# Launch brief', 200, headers: {
            'content-type': ['text/markdown'],
            'content-disposition': ['attachment; filename="launch-brief.md"'],
          }),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });
    final container = ProviderContainer(
      retry: retryOnlyNetworkErrors,
      overrides: [
        sharedPreferencesProvider.overrideWithValue(preferences),
        sessionStoreProvider.overrideWithValue(store),
        apiClientProvider.overrideWithValue(fakeClient(adapter, store)),
        deviceIntegrityProvider.overrideWith((ref) async => DeviceIntegrity.unknown),
        fileSharerProvider.overrideWithValue((file) async => shared.add(file)),
      ],
    );
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
    await tester.pumpAndSettle();
    container.read(routerProvider).go('/studio');
    await tester.pumpAndSettle();
    // The Studio opens on Start; the queue is the third tab.
    await tester.ensureVisible(find.text('Live production queue'));
    await tester.tap(find.text('Live production queue'));
    await tester.pumpAndSettle();
    expect(find.text('No Studio jobs yet.'), findsOneWidget);

    await tester.tap(find.byKey(const Key('new-studio-job')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('studio-title')), 'Launch brief');
    await tester.enterText(find.byKey(const Key('studio-brief')), 'A brief for the launch campaign.');
    await tester.tap(find.byKey(const Key('studio-queue')));
    await tester.pumpAndSettle();

    final sent = created! as Map;
    expect(sent['department'], 'text');
    expect(sent['language'], 'en');
    expect(sent['programming_language'], isNull);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);

    status = 'completed';
    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    expect(find.text('completed'), findsOneWidget);

    await tester.ensureVisible(find.text('Asset library & history'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Asset library & history'));
    await tester.pumpAndSettle();
    expect(find.textContaining('launch-brief.md'), findsOneWidget);
    await tester.tap(find.byKey(const Key('download-a1')));
    await tester.pumpAndSettle();
    expect(shared.single.filename, 'launch-brief.md');
    expect(utf8.decode(shared.single.bytes), '# Launch brief');
    expect(adapter.paths, contains('/api/v1/studio/assets/a1/download'));
  });

  test('download file names never carry a path', () {
    expect(filenameFromDisposition('attachment; filename="../../etc/passwd"', 'x'), 'passwd');
    expect(filenameFromDisposition("attachment; filename*=UTF-8''%D8%AA%D9%82%D8%B1%D9%8A%D8%B1.md", 'x'), 'تقرير.md');
    expect(filenameFromDisposition(null, 'fallback.bin'), 'fallback.bin');
  });
}
