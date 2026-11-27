import 'dart:convert';

import 'package:aionex/src/app.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/providers.dart';
import 'package:aionex/src/core/router/app_router.dart';
import 'package:aionex/src/core/security/device_security.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_api.dart';

Object? body(RequestOptions request) => request.data is String ? jsonDecode(request.data as String) : request.data;

Map<String, Object?> access(String source) => {
      'enabled': true,
      'granted': true,
      'source': source,
      'profiles': ['passive', 'standard'],
      'reports_available': true,
      'limits': {'max_verified_targets': 3, 'max_scans_per_month': 10},
      'usage': {'verified_targets': 1, 'scans_this_month': 1},
      'verification': {'reverify_after_days': 30},
    };

const finding = {
  'id': 'f1',
  'scan_id': 's1',
  'target_id': 't1',
  'title': 'Missing HSTS header',
  'severity': 'high',
  'category': 'headers',
  'state': 'confirmed',
  'cwe': 'CWE-319',
  'location': 'https://app.example.com/',
  'remediation': 'Send Strict-Transport-Security.',
};

Future<ProviderContainer> start(WidgetTester tester, Map<String, Object?> sent, {String source = 'owner'}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final store = MemorySessionStore(refreshToken: 'saved');
  var status = 'regression_passed';
  final adapter = FakeAdapter((request) async {
    final path = request.uri.path.replaceFirst('/api/v1', '');
    return switch ((request.method, path)) {
      ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
      ('GET', '/auth/me') => jsonBody(200, userJson()),
      ('GET', '/security-lab/access') => jsonBody(200, access(source)),
      ('GET', '/security-lab/targets') => jsonBody(200, <Object>[]),
      ('GET', '/security-lab/scans') => jsonBody(200, <Object>[]),
      ('GET', '/security-lab/tools') => jsonBody(200, [
          {'id': 'zap', 'category': 'dast', 'available': true, 'active': true, 'requires_clone': false},
          {'id': 'semgrep', 'category': 'sast', 'available': false, 'active': false, 'requires_clone': true},
        ]),
      ('GET', '/security-lab/remediations') => jsonBody(200, [
          {'id': 'r1', 'finding_id': 'f1aaaaaaaaaa', 'status': status, 'updated_at': '2026-11-27T10:00:00Z'},
        ]),
      ('POST', '/security-lab/remediations/r1/retest') => () {
          sent['retest'] = true;
          status = 'retest_queued';
          return jsonBody(202, {'remediation': <String, Object>{}, 'scan': <String, Object>{}});
        }(),
      ('POST', '/security-lab/remediations/r1/finalize') => () {
          sent['finalize'] = true;
          status = 'verified_fixed';
          return jsonBody(200, <String, Object>{});
        }(),
      ('GET', '/security-lab/scans/s1/findings') => jsonBody(200, [finding]),
      ('GET', '/security-lab/scans/s1/report') => jsonBody(200, {
          'scan': {'id': 's1', 'profile': 'standard', 'completed_at': '2026-11-27T09:00:00Z'},
          'target': {'id': 't1', 'origin': 'https://app.example.com'},
          'severity_counts': {'high': 1},
          'findings_by_severity': {
            'high': [finding],
          },
          'generated_at': '2026-11-27T09:05:00Z',
        }),
      ('POST', '/security-lab/remediations') => () {
          sent['request'] = body(request);
          return jsonBody(202, {'id': 'r2', 'finding_id': 'f1', 'status': 'queued'});
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
  return container;
}

Future<void> reveal(WidgetTester tester, Finder finder) async {
  await tester.scrollUntilVisible(finder, 200, scrollable: find.byType(Scrollable).hitTestable().first);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('engine inventory and remediation steps: retest, then confirm', (tester) async {
    final sent = <String, Object?>{};
    final container = await start(tester, sent);
    container.read(routerProvider).go('/security-lab');
    await tester.pumpAndSettle();

    await reveal(tester, find.byKey(const Key('security-tool-semgrep')));
    expect(find.textContaining('isolated clone only'), findsOneWidget);
    await reveal(tester, find.byKey(const Key('remediation-retest-r1')));
    await tester.tap(find.byKey(const Key('remediation-retest-r1')));
    await tester.pumpAndSettle();
    expect(sent['retest'], isTrue);
    await reveal(tester, find.byKey(const Key('remediation-finalize-r1')));
    await tester.tap(find.byKey(const Key('remediation-finalize-r1')));
    await tester.pumpAndSettle();
    expect(sent['finalize'], isTrue);
    expect(find.text('Fixed and verified'), findsOneWidget);
  });

  testWidgets('subscribers do not see the engine inventory', (tester) async {
    final container = await start(tester, {}, source: 'subscription');
    container.read(routerProvider).go('/security-lab');
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('security-tools')), findsNothing);
  });

  testWidgets('the report shows dates and counts, copies as text, and a confirmed finding can request a fix',
      (tester) async {
    final sent = <String, Object?>{};
    final clipboard = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') clipboard.add((call.arguments as Map)['text'] as String);
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
    final container = await start(tester, sent);
    container.read(routerProvider).go('/security-lab/scans/s1');
    await tester.pumpAndSettle();

    expect(find.text('https://app.example.com'), findsOneWidget);
    expect(find.byKey(const Key('security-report-meta')), findsOneWidget);
    expect(find.text('High · 1'), findsOneWidget);

    await tester.tap(find.byKey(const Key('security-copy-report')));
    await tester.pumpAndSettle();
    expect(clipboard.single, contains('[High] Missing HSTS header (CWE-319)'));
    expect(clipboard.single, contains('Send Strict-Transport-Security.'));

    await tester.tap(find.text('Missing HSTS header'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('finding-fix-f1')));
    await tester.pumpAndSettle();
    expect(sent['request'], {'finding_id': 'f1'});
  });
}
