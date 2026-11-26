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

const course = {
  'id': 'c1',
  'organization_id': 'o1',
  'code': 'SAFE-101',
  'title': 'Safety basics',
  'description': 'Site safety for new staff.',
  'competencies': ['ppe'],
  'passing_score': 80.0,
  'status': 'active',
  'version': 1,
};

Map<String, Object?> package(String status) => {
      'id': 'p1',
      'course_id': 'c1',
      'status': status,
      'version': 1,
      'lesson_count': 4,
      'download_ready': status == 'approved',
      'archive_sha256': status == 'queued' ? null : 'abcdef0123456789abcdef',
      'error_code': null,
      'created_at': '2026-11-26T10:00:00Z',
    };

Future<ProviderContainer> start(WidgetTester tester, FakeAdapter adapter, {List<DownloadedFile>? shared}) async {
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
      fileSharerProvider.overrideWithValue((file) async => shared?.add(file)),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
  await tester.pumpAndSettle();
  container.read(routerProvider).go('/academy');
  await tester.pumpAndSettle();
  return container;
}

void main() {
  testWidgets('a course is created, its package built, approved and downloaded', (tester) async {
    final user = userJson(role: 'Member', plan: 'professional', permissions: ['academy:read', 'academy:write', 'academy:assess']);
    var courses = <Object>[];
    var status = 'none';
    Object? createdCourse;
    Object? queued;
    Object? review;
    final shared = <DownloadedFile>[];
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, {...grantJson(), 'user': user}),
        ('GET', '/auth/me') => jsonBody(200, user),
        ('GET', '/academy/courses') => jsonBody(200, courses),
        ('POST', '/academy/courses') => () {
            createdCourse = body(request);
            courses = [course];
            return jsonBody(201, course);
          }(),
        ('GET', '/academy/courses/c1/packages') => jsonBody(200, status == 'none' ? <Object>[] : [package(status)]),
        ('POST', '/academy/courses/c1/packages') => () {
            queued = body(request);
            status = 'building';
            return jsonBody(202, package('queued'));
          }(),
        ('POST', '/academy/packages/p1/review') => () {
            review = body(request);
            status = 'approved';
            return jsonBody(200, package('approved'));
          }(),
        ('GET', '/academy/packages/p1/download') => ResponseBody.fromString('PK', 200, headers: {
            'content-type': ['application/zip'],
            'content-disposition': ['attachment; filename="safe-101-v1.zip"'],
          }),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });
    await start(tester, adapter, shared: shared);
    expect(find.text('No Academy courses yet.'), findsOneWidget);

    await tester.tap(find.byKey(const Key('new-course')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('course-code')), 'SAFE-101');
    await tester.enterText(find.byKey(const Key('course-title')), 'Safety basics');
    await tester.tap(find.byKey(const Key('course-create')));
    await tester.pumpAndSettle();
    expect((createdCourse! as Map)['passing_score'], 80.0);
    expect(find.text('Safety basics'), findsOneWidget);
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('build-c1')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('package-domain')), 'Workplace safety');
    await tester.enterText(find.byKey(const Key('package-audience')), 'New staff');
    await tester.tap(find.byKey(const Key('package-queue')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    final sent = queued! as Map;
    expect(sent['locales'], ['ar', 'en', 'fr', 'de', 'es', 'tr']);
    expect(sent['module_count'], 2);
    expect((sent['idempotency_key'] as String).length, greaterThanOrEqualTo(4));
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();

    status = 'review_pending';
    await tester.pump(const Duration(seconds: 4));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byKey(const Key('approve-p1')), findsOneWidget);
    await tester.tap(find.byKey(const Key('approve-p1')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('review-notes')), 'Looks right');
    await tester.tap(find.byKey(const Key('review-confirm')));
    await tester.pumpAndSettle();
    expect(review, {'approved': true, 'notes': 'Looks right'});

    await tester.tap(find.byKey(const Key('download-package-p1')));
    await tester.pumpAndSettle();
    expect(shared.single.filename, 'safe-101-v1.zip');
  });

  testWidgets('the free plan sees the paid-plan notice and never calls the Academy', (tester) async {
    final adapter = FakeAdapter((request) async {
      final path = request.uri.path.replaceFirst('/api/v1', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
        ('GET', '/auth/me') => jsonBody(200, userJson()),
        _ => jsonBody(404, {'detail': 'not found'}),
      };
    });
    await start(tester, adapter);
    expect(find.text('Academy requires an eligible paid plan'), findsOneWidget);
    expect(find.byKey(const Key('new-course')), findsNothing);
    expect(adapter.paths.where((p) => p.contains('/academy')), isEmpty);
  });
}
