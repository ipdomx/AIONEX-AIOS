import 'dart:convert';

import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/auth/session_store.dart';
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

Map<String, Object?> capability(String id, {required bool available, List<String> departments = const [], String reason = 'available', List<String> gates = const []}) => {
      'capability_id': id,
      'title': id,
      'launch_surface': id == 'sector-solutions' ? 'studio-sectors' : 'studio',
      'departments': departments,
      'external_gates': gates,
      'available': available,
      'availability_reason': available ? 'available' : reason,
    };

Future<ProviderContainer> start(WidgetTester tester, Map<String, Object?> sent) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final store = MemorySessionStore(refreshToken: 'saved');
  final adapter = FakeAdapter((request) async {
    final path = request.uri.path.replaceFirst('/api/v1', '');
    return switch ((request.method, path)) {
      ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
      ('GET', '/auth/me') => jsonBody(200, userJson()),
      ('GET', '/studio/jobs') => jsonBody(200, <Object>[]),
      ('GET', '/studio/assets') => jsonBody(200, <Object>[]),
      ('GET', '/projects') => jsonBody(200, <Object>[]),
      ('GET', '/workspaces') => jsonBody(200, [
          {'id': 'w1', 'name': 'Main'},
        ]),
      ('GET', '/studio/departments') => jsonBody(200, {
          'departments': [
            {'id': 'text', 'name': 'Text Studio', 'outputs': ['outline']},
            {'id': 'video', 'name': 'Video Studio', 'outputs': ['mp4']},
          ],
        }),
      ('GET', '/studio/hub') => jsonBody(200, {
          'capabilities': [
            capability('prompt-text', available: true, departments: ['text']),
            capability('video-motion', available: false, departments: ['video'], reason: 'plan_not_supported'),
            capability('sector-solutions', available: true, gates: ['legal review']),
          ],
        }),
      ('GET', '/studio/sector-packs') => jsonBody(200, {
          'capability': capability('sector-solutions', available: true),
          'packs': [
            {
              'key': 'clinic',
              'title': 'Clinic operations',
              'objective': 'Run appointments and records.',
              'audience': 'Clinics',
              'roles': ['Doctor', 'Reception'],
              'entity_count': 6,
              'workflow_count': 4,
              'workflows': ['Booking', 'Check-in'],
              'safety_boundaries': ['No diagnosis'],
              'external_gates': ['Health licence'],
              'domain_blueprint': {'version': 3},
            },
          ],
        }),
      ('POST', '/projects') => () {
          ((sent['projects'] ??= <Object?>[]) as List<Object?>).add(body(request));
          final b = body(request)! as Map;
          return jsonBody(201, {'id': 'p1', 'name': b['name'], 'status': 'active', 'workspace': {'id': 'w1', 'name': 'Main'}});
        }(),
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
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AionexApp()));
  await tester.pumpAndSettle();
  container.read(routerProvider).go('/studio');
  await tester.pumpAndSettle();
  return container;
}

void main() {
  testWidgets('Start tab: readiness, a ready preset opens the request prefilled, a closed one is disabled',
      (tester) async {
    await start(tester, {});
    expect(find.textContaining('2 · Available to your account now'), findsOneWidget);
    expect(find.textContaining('This capability is not available on your current organization plan.'), findsOneWidget);

    // Video is not in this plan: tapping does nothing.
    await tester.ensureVisible(find.byKey(const Key('studio-preset-video')));
    await tester.tap(find.byKey(const Key('studio-preset-video')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('studio-department')), findsNothing);

    await tester.ensureVisible(find.byKey(const Key('studio-preset-prompts')));
    await tester.tap(find.byKey(const Key('studio-preset-prompts')));
    await tester.pumpAndSettle();
    final department = tester.widget<DropdownButtonFormField<String>>(find.byKey(const Key('studio-department')));
    expect(department.initialValue, 'text');
    expect(find.text('structured prompt system'), findsOneWidget);
    // The video department is left out of the list for this plan.
    await tester.tap(find.byKey(const Key('studio-department')));
    await tester.pumpAndSettle();
    expect(find.text('Video Studio'), findsNothing);
  });

  testWidgets('Sectors tab: a pack and a custom sector become projects in the chosen workspace', (tester) async {
    final sent = <String, Object?>{};
    await start(tester, sent);
    await tester.ensureVisible(find.byKey(const Key('studio-preset-sector')));
    await tester.tap(find.byKey(const Key('studio-preset-sector')));
    await tester.pumpAndSettle();
    expect(find.text('Clinic operations'), findsOneWidget);
    expect(find.text('6 entities'), findsOneWidget);

    await tester.tap(find.byKey(const Key('sector-use-clinic')));
    await tester.pumpAndSettle();
    final pack = (sent['projects']! as List).first as Map;
    expect(pack['name'], 'Clinic operations');
    expect(pack['workspace_id'], 'w1');
    expect(pack['tags'], ['phase36m', 'domain-blueprint-v3', 'sector:clinic']);
    expect(pack['description'] as String, contains('Domain Blueprint v3: {"version":3}'));

    await tester.ensureVisible(find.byKey(const Key('sector-custom-name')));
    await tester.enterText(find.byKey(const Key('sector-custom-name')), 'Bakery');
    await tester.enterText(find.byKey(const Key('sector-custom-audience')), 'Neighbourhood bakeries');
    await tester.enterText(find.byKey(const Key('sector-custom-objective')), 'Take orders and plan baking.');
    await tester.ensureVisible(find.byKey(const Key('sector-custom-create')));
    await tester.tap(find.byKey(const Key('sector-custom-create')));
    await tester.pumpAndSettle();
    final custom = (sent['projects']! as List).last as Map;
    expect(custom['name'], 'Bakery');
    expect(custom['tags'], ['phase36m', 'domain-blueprint-v3', 'sector:custom']);
    expect(custom['description'] as String, contains('Audience: Neighbourhood bakeries'));
  });
}
