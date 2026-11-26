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

const project = {
  'id': 'p1',
  'name': 'Launch site',
  'slug': 'launch-site',
  'description': 'Marketing site',
  'status': 'active',
  'priority': 'high',
  'progress': 40,
  'workspace_id': 'w1',
  'workspace': 'Main',
  'owner_id': 'u1',
  'owner': 'Ahmed',
  'team_count': 1,
  'task_count': 3,
  'tags': <String>[],
  'created_at': '2026-11-01T10:00:00Z',
  'updated_at': '2026-11-02T10:00:00Z',
};

Map<String, Object?> execution(String status, {bool approved = false}) => {
      'id': 'e1',
      'project_id': 'p1',
      'mode': 'full',
      'provider': 'provider-neutral',
      'status': status,
      'stage': status == 'completed' ? 'review' : 'cognitive_review',
      'progress': status == 'completed' ? 100 : 30,
      'budget_cap_usd': 0.05,
      'calculated_cost_usd': 0,
      'requests_count': 0,
      'retries_count': 0,
      'input_tokens': 0,
      'output_tokens': 0,
      'total_tokens': 0,
      'approved': approved,
      'readiness_score': status == 'completed' ? 0.96 : null,
      'result': status == 'completed'
          ? {
              'success': true,
              'status': 'completed',
              'provider': 'local',
              'requests_count': 0,
              'retries_count': 0,
              'input_tokens': 0,
              'output_tokens': 0,
              'total_tokens': 0,
              'calculated_cost': 0,
              'budget_cap': 0.05,
              'total_duration': 1,
              'approved': approved,
              'readiness_score': 0.96,
              'blocking_findings': approved ? <String>[] : ['owner approval is required'],
              'rework_plan': <String>[],
            }
          : null,
      'evidence_available': status == 'completed',
      'created_at': '2026-11-26T10:00:00Z',
    };

void main() {
  testWidgets('an owner runs the governed cycle, follows it, approves and downloads', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.6;
    addTearDown(tester.view.reset);
    final owner = userJson(role: 'Owner', plan: 'professional');
    var current = <Object>[];
    final sent = <String, Object?>{};
    final shared = <DownloadedFile>[];
    SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
    final preferences = await SharedPreferences.getInstance();
    final store = MemorySessionStore(refreshToken: 'saved');
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, {...grantJson(), 'user': owner}),
        ('GET', '/auth/me') => jsonBody(200, owner),
        ('GET', '/projects') => jsonBody(200, [project]),
        ('GET', '/auth/free-tier') => jsonBody(200, {'free_tier': false}),
        ('GET', '/projects/p1/executions') => jsonBody(200, current),
        ('POST', '/projects/p1/executions') => () {
            sent['start'] = body(request);
            current = [execution('running')];
            return jsonBody(202, execution('queued'));
          }(),
        ('POST', '/projects/p1/executions/e1/approve') => () {
            sent['approve'] = body(request);
            current = [execution('completed', approved: true)];
            return jsonBody(200, execution('completed', approved: true));
          }(),
        ('GET', '/projects/p1/executions/e1/download') => ResponseBody.fromString('PK', 200, headers: {
            'content-type': ['application/zip'],
            'content-disposition': ['attachment; filename="launch-site-delivery.zip"'],
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
    container.read(routerProvider).go('/projects/p1');
    await tester.pumpAndSettle();
    expect(find.text('Full governed project cycle'), findsOneWidget);

    await tester.tap(find.byKey(const Key('execution-start')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('execution-confirm')));
    await tester.pumpAndSettle();
    expect(sent['start'], {'mode': 'full', 'confirm_external_processing': true});
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(find.textContaining('Cognitive cells and sages'), findsOneWidget);

    current = [execution('completed')];
    await tester.pump(const Duration(seconds: 4));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.textContaining('waiting only for the Organization Owner'), findsOneWidget);
    await tester.tap(find.byKey(const Key('execution-approve')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('execution-confirm')));
    await tester.pumpAndSettle();
    expect(sent['approve'], {'confirm_owner_approval': true, 'note': null});
    expect(find.textContaining('passed every retained evidence gate'), findsOneWidget);

    await tester.tap(find.byKey(const Key('execution-download')));
    await tester.pumpAndSettle();
    expect(shared.single.filename, 'launch-site-delivery.zip');
  });
}
