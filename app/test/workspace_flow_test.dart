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

Map<String, Object?> project({String id = 'p1', String name = 'Launch site'}) => {
      'id': id,
      'name': name,
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
      'tags': ['web'],
      'created_at': '2026-11-01T10:00:00Z',
      'updated_at': '2026-11-02T10:00:00Z',
    };

Map<String, Object?> conversation({String status = 'open', int used = 0}) => {
      'id': 'c1',
      'project_id': 'p1',
      'user_id': 'u1',
      'title': 'Plan the launch',
      'status': status,
      'effective_status': status,
      'messages_used': used,
      'messages_allowed': 20,
      'opened_at': '2026-11-23T10:00:00Z',
      'expires_at': '2026-11-23T12:00:00Z',
      'seconds_remaining': 3600,
      'version': 1,
      'last_job_id': null,
      'priority': 1,
    };

Map<String, Object?> policy() => {
      'values': {'enabled': true, 'max_message_characters': 2000, 'messages_per_day': 50, 'lifetime_message_credits': 0},
      'versions': <String, Object?>{},
      'credit_unit': 'message',
      'usage': {'day': '2026-11-23', 'day_messages': 1, 'total_message_credits': 1},
    };

Future<ProviderContainer> pumpSignedIn(WidgetTester tester, Map<String, ResponseBody Function(RequestOptions)> routes,
    {List<RequestOptions>? log}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final store = MemorySessionStore(refreshToken: 'saved');
  final adapter = FakeAdapter((request) async {
    log?.add(request);
    final path = request.uri.path.replaceFirst('/api/v1', '');
    final key = '${request.method} $path';
    if (routes.containsKey(key)) return routes[key]!(request);
    return switch (path) {
      '/auth/refresh' => jsonBody(200, grantJson()),
      '/auth/me' => jsonBody(200, userJson()),
      '/auth/free-tier' => jsonBody(200, {
          'plan': 'free',
          'plan_name': 'Free',
          'free_tier': true,
          'limits': {'projects': 3, 'user_messages': 100, 'assistant_responses': 100, 'storage_bytes': 1073741824},
          'usage': {'projects': 1, 'user_messages': 10, 'assistant_responses': 9, 'storage_bytes': 52428800},
          'remaining': {'projects': 2, 'user_messages': 90, 'assistant_responses': 91, 'storage_bytes': 1021313024},
          'period_ends_at': '2026-12-01T00:00:00Z',
        }),
      '/projects' => jsonBody(200, [project()]),
      _ => jsonBody(404, {'detail': 'not found'}),
    };
  });
  final container = ProviderContainer(
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

Future<void> go(WidgetTester tester, ProviderContainer container, String path) async {
  container.read(routerProvider).go(path);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the dashboard shows the live quota and recent projects', (tester) async {
    await pumpSignedIn(tester, {});

    expect(find.text('1 / 3'), findsOneWidget);
    expect(find.text('90 / 100'), findsOneWidget);
    expect(find.text('50 MB / 1.0 GB'), findsOneWidget);
    expect(find.text('Launch site'), findsOneWidget);
  });

  testWidgets('a project is created in the only workspace', (tester) async {
    Object? sent;
    final container = await pumpSignedIn(tester, {
      'GET /workspaces': (_) => jsonBody(200, [
            {'id': 'w1', 'name': 'Main', 'slug': 'main', 'organization_id': 'o1', 'status': 'active'},
          ]),
      'POST /projects': (request) {
        sent = body(request);
        return jsonBody(201, project(id: 'p2', name: 'Mobile app'));
      },
    });
    await go(tester, container, '/projects');

    await tester.tap(find.byKey(const Key('new-project')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('project-name')), 'Mobile app');
    await tester.tap(find.byKey(const Key('project-create')));
    await tester.pumpAndSettle();

    expect(sent, {'name': 'Mobile app', 'description': null, 'priority': 'medium', 'workspace_id': 'w1', 'tags': <String>[]});
  });

  testWidgets('a message is sent once and the answer arrives by polling', (tester) async {
    var phase = 0;
    final sends = <Object?>[];
    final container = await pumpSignedIn(tester, {
      'GET /project-conversations/policy': (_) => jsonBody(200, policy()),
      'GET /project-conversations/agents': (_) => jsonBody(200, [
            {'id': 'a1', 'name': 'AIONEX', 'provider': 'aionex', 'model': 'x', 'external_processing': false, 'platform_shared': true},
          ]),
      'GET /project-conversations/c1/messages': (_) => jsonBody(200, {
            'conversation': conversation(used: phase == 0 ? 0 : 1),
            'messages': [
              if (phase >= 1)
                {
                  'id': 'm1',
                  'ordinal': 1,
                  'user_message': 'Draft a launch checklist',
                  'assistant_message': phase == 2 ? 'Here is the checklist.' : null,
                  'status': phase == 2 ? 'completed' : 'running',
                  'error': null,
                  'created_at': '2026-11-23T10:01:00Z',
                  'started_at': null,
                  'updated_at': '2026-11-23T10:01:00Z',
                  'heartbeat_age_seconds': null,
                  'completed_at': null,
                },
            ],
            'history_limit': 50,
          }),
      'POST /project-conversations/c1/messages': (request) {
        sends.add(body(request));
        phase = 1;
        return jsonBody(202, {'job_id': 'j1', 'status': 'queued', 'duplicate': false});
      },
    });
    await go(tester, container, '/conversations/c1');
    expect(find.text('Send your first message to the configured assistant.'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('conversation-message')), 'Draft a launch checklist');
    await tester.pump();
    await tester.tap(find.byKey(const Key('conversation-send')));
    await tester.pumpAndSettle();

    expect(find.textContaining('Still working'), findsOneWidget);
    final send = sends.single! as Map;
    expect(send['message'], 'Draft a launch checklist');
    expect(send['agent_id'], 'a1');
    expect((send['request_id'] as String).length, 32);

    phase = 2;
    await tester.pump(const Duration(seconds: 3));
    await tester.pumpAndSettle();
    expect(find.text('Here is the checklist.'), findsOneWidget);
    expect(sends, hasLength(1));
  });

  testWidgets('an external assistant needs explicit consent before sending', (tester) async {
    final container = await pumpSignedIn(tester, {
      'GET /project-conversations/policy': (_) => jsonBody(200, policy()),
      'GET /project-conversations/agents': (_) => jsonBody(200, [
            {'id': 'a2', 'name': 'External', 'provider': 'x', 'model': 'y', 'external_processing': true, 'platform_shared': false},
          ]),
      'GET /project-conversations/c1/messages': (_) =>
          jsonBody(200, {'conversation': conversation(), 'messages': <Object>[], 'history_limit': 50}),
    });
    await go(tester, container, '/conversations/c1');

    await tester.enterText(find.byKey(const Key('conversation-message')), 'Hello');
    await tester.pump();
    IconButton send() => tester.widget<IconButton>(find.byKey(const Key('conversation-send')));
    expect(send().onPressed, isNull);
    await tester.tap(find.byKey(const Key('external-consent')));
    await tester.pump();
    expect(send().onPressed, isNotNull);
  });

  testWidgets('a closed conversation cannot be written to', (tester) async {
    final container = await pumpSignedIn(tester, {
      'GET /project-conversations/policy': (_) => jsonBody(200, policy()),
      'GET /project-conversations/agents': (_) => jsonBody(200, <Object>[]),
      'GET /project-conversations/c1/messages': (_) =>
          jsonBody(200, {'conversation': conversation(status: 'closed'), 'messages': <Object>[], 'history_limit': 50}),
    });
    await go(tester, container, '/conversations/c1');

    expect(find.textContaining('This conversation is closed'), findsOneWidget);
    expect(find.byKey(const Key('conversation-message')), findsNothing);
  });

  testWidgets('a support request is opened and answered', (tester) async {
    final replies = <Object?>[];
    Map<String, Object?> ticket() => {
          'id': 't1',
          'organization_id': 'o1',
          'requester_id': 'u1',
          'subject': 'Invoice question',
          'category': 'billing',
          'priority': 'normal',
          'status': 'open',
          'message_count': 1 + replies.length,
          'last_message_at': '2026-11-23T10:00:00Z',
          'created_at': '2026-11-23T10:00:00Z',
          'updated_at': '2026-11-23T10:00:00Z',
          'messages': [
            {'id': 'm1', 'support_request_id': 't1', 'sender_id': 'u1', 'visibility': 'requester', 'message': 'Where is my invoice?', 'attachments': <Object>[], 'created_at': '2026-11-23T10:00:00Z'},
            for (final reply in replies)
              {'id': 'm2', 'support_request_id': 't1', 'sender_id': 'u1', 'visibility': 'requester', 'message': (reply! as Map)['message'], 'attachments': <Object>[], 'created_at': '2026-11-23T10:05:00Z'},
          ],
        };
    Object? created;
    final container = await pumpSignedIn(tester, {
      'GET /support/requests': (_) => jsonBody(200, created == null ? <Object>[] : [ticket()]),
      'POST /support/requests': (request) {
        created = body(request);
        return jsonBody(201, ticket());
      },
      'GET /support/requests/t1': (_) => jsonBody(200, ticket()),
      'POST /support/requests/t1/messages': (request) {
        replies.add(body(request));
        return jsonBody(201, {'id': 'm2'});
      },
    });
    await go(tester, container, '/support');
    expect(find.text('No support requests yet.'), findsOneWidget);

    await tester.tap(find.byKey(const Key('new-ticket')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('ticket-subject')), 'Invoice question');
    await tester.enterText(find.byKey(const Key('ticket-message')), 'short');
    await tester.tap(find.byKey(const Key('ticket-create')));
    await tester.pumpAndSettle();
    expect(created, isNull, reason: 'messages under 10 characters are stopped locally');

    await tester.enterText(find.byKey(const Key('ticket-message')), 'Where is my invoice?');
    await tester.tap(find.byKey(const Key('ticket-create')));
    await tester.pumpAndSettle();
    expect(created, {'subject': 'Invoice question', 'message': 'Where is my invoice?', 'category': 'general', 'priority': 'normal'});
    expect(find.text('Where is my invoice?'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('ticket-reply')), 'Any update?');
    await tester.pump();
    await tester.tap(find.byKey(const Key('ticket-send')));
    await tester.pumpAndSettle();
    expect(replies.single, {'message': 'Any update?', 'visibility': 'requester'});
    expect(find.text('Any update?'), findsOneWidget);
  });
}
