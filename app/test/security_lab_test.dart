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

Map<String, Object?> access({bool granted = true}) => {
      'enabled': true,
      'granted': granted,
      'level': granted ? 'subscriber' : null,
      'profiles': ['passive', 'standard'],
      'deep_validation_requires_clone': true,
      'reports_available': false,
      'limits': {'max_verified_targets': 3, 'max_scans_per_month': 10, 'max_concurrent_scans': 1},
      'usage': {'targets': 1, 'verified_targets': 0, 'scans_this_month': 0, 'active_scans': 0, 'period_start': 'x', 'period_end': 'y'},
      'verification': {'methods': ['http_file', 'dns_txt'], 'http_file_path': '/.well-known/aionex', 'dns_record_prefix': '_aionex', 'dns_value_prefix': 'aionex=', 'reverify_after_days': 30},
    };

Map<String, Object?> target(String status) => {
      'id': 't1',
      'project_id': null,
      'kind': 'external',
      'origin': 'https://shop.example.com',
      'hostname': 'shop.example.com',
      'authorization_status': status,
      'verification_method': 'http_file',
      'active_scan_allowed': status == 'verified',
      'status': 'active',
      'metadata': <String, Object>{},
      'verified_at': status == 'verified' ? '2026-11-26T10:00:00Z' : null,
    };

Map<String, Object?> scan(String status) => {
      'id': 's1234567890',
      'project_id': null,
      'target_id': 't1',
      'profile': 'standard',
      'status': status,
      'execution_mode': 'worker',
      'tool_plan': <Object>[],
      'summary': status == 'completed'
          ? {'finding_count': 1, 'severity': {'high': 1}}
          : <String, Object>{},
      'error_code': null,
      'error_message': null,
      'created_at': '2026-11-26T10:05:00Z',
    };

Future<FakeAdapter> start(WidgetTester tester, Map<String, Object?> sent, {bool granted = true}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final store = MemorySessionStore(refreshToken: 'saved');
  var targets = <Object>[];
  var scans = <Object>[];
  final adapter = FakeAdapter((request) async {
    final path = request.uri.path.replaceFirst('/api/v1', '');
    return switch ((request.method, path)) {
      ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
      ('GET', '/auth/me') => jsonBody(200, userJson()),
      ('GET', '/security-lab/access') => granted ? jsonBody(200, access()) : jsonBody(403, {'detail': {'code': 'SECURITY_PLAN_REQUIRED'}}),
      ('GET', '/security-lab/targets') => jsonBody(200, targets),
      ('GET', '/security-lab/scans') => jsonBody(200, scans),
      ('POST', '/security-lab/targets/external') => () {
          sent['add'] = body(request);
          targets = [target('pending')];
          return jsonBody(201, {
            ...target('pending'),
            'verification': {
              'method': 'http_file',
              'path': '/.well-known/aionex-verify.txt',
              'challenge': 'chal-123',
              'methods': {
                'http_file': {
                  'method': 'http_file',
                  'available': true,
                  'path': '/.well-known/aionex-verify.txt',
                  'url': 'https://shop.example.com/.well-known/aionex-verify.txt',
                  'content': 'aionex-site-verification=chal-123',
                },
                'dns_txt': {'method': 'dns_txt', 'available': true, 'record_name': '_aionex.shop.example.com', 'record_type': 'TXT', 'record_value': 'aionex=chal-123'},
              },
            },
          });
        }(),
      ('POST', '/security-lab/targets/t1/verify') => () {
          sent['verify'] = body(request);
          targets = [target('verified')];
          return jsonBody(200, target('verified'));
        }(),
      ('POST', '/security-lab/scans') => () {
          sent['scan'] = body(request);
          scans = [scan('completed')];
          return jsonBody(201, scan('queued'));
        }(),
      ('GET', '/security-lab/scans/s1234567890/findings') => jsonBody(200, [
          {
            'id': 'f1',
            'scan_id': 's1234567890',
            'target_id': 't1',
            'source': 'headers',
            'category': 'headers',
            'title': 'Missing Content-Security-Policy',
            'severity': 'high',
            'confidence': 0.9,
            'state': 'open',
            'fingerprint': 'x',
            'cwe': 'CWE-693',
            'owasp': null,
            'location': 'https://shop.example.com/',
            'evidence': <String, Object>{},
            'remediation': 'Send a strict Content-Security-Policy header.',
            'verified_at': null,
            'resolved_at': null,
          },
        ]),
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
  container.read(routerProvider).go('/security-lab');
  await tester.pumpAndSettle();
  return adapter;
}

void main() {
  testWidgets('a site is added, ownership verified, scanned and its findings read', (tester) async {
    final copied = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied.add((call.arguments as Map)['text'] as String);
      return null;
    });
    final sent = <String, Object?>{};
    await start(tester, sent);
    expect(find.text('No websites yet. Add your first website above.'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('security-origin')), 'https://shop.example.com');
    await tester.tap(find.byKey(const Key('security-add')));
    await tester.pumpAndSettle();
    expect(sent['add'], {'origin': 'https://shop.example.com'});
    expect(find.text('aionex-site-verification=chal-123'), findsOneWidget);
    await tester.tap(find.byTooltip('Copy').last);
    await tester.pumpAndSettle();
    expect(copied, ['aionex-site-verification=chal-123']);

    await tester.tap(find.byKey(const Key('security-verify-now')));
    await tester.pumpAndSettle();
    expect(sent['verify'], {'challenge': 'chal-123', 'method': 'http_file'});
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.byKey(const Key('security-scan')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('security-scan')));
    await tester.pumpAndSettle();
    expect(sent['scan'], {'target_id': 't1', 'profile': 'passive'});
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.byKey(const Key('security-view-s1234567890')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('security-view-s1234567890')));
    await tester.pumpAndSettle();
    expect(find.text('Missing Content-Security-Policy'), findsOneWidget);
    await tester.tap(find.text('Missing Content-Security-Policy'));
    await tester.pumpAndSettle();
    expect(find.text('Send a strict Content-Security-Policy header.'), findsOneWidget);
  });

  testWidgets('without the top plan the upgrade notice shows', (tester) async {
    final adapter = await start(tester, {}, granted: false);
    expect(find.text('Website security scanning is a top-plan feature'), findsOneWidget);
    expect(adapter.paths.where((p) => p.contains('/security-lab/scans')), isEmpty);
  });
}
