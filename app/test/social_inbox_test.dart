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

Map<String, Object?> conversation({int unread = 1, bool windowOpen = true, List<Object> messages = const []}) => {
      'id': 'c1',
      'account_id': 'acc1',
      'account_name': 'IPDOMX Page',
      'account_status': 'active',
      'provider': 'instagram',
      'channel': 'dm',
      'participant_name': 'Sara',
      'status': 'open',
      'unread_count': unread,
      'last_message_at': '2026-11-26T10:00:00Z',
      'last_message_preview': 'Do you ship to Dubai?',
      'reply_window': {'applies': true, 'open': windowOpen, 'expires_at': '2026-11-27T10:00:00Z'},
      'version': 1,
      'messages': messages,
    };

const inbound = {
  'id': 'm1',
  'direction': 'inbound',
  'kind': 'dm',
  'author_name': 'Sara',
  'body': '<b>Do you ship to Dubai?</b>',
  'attachments': <Object>[],
  'hidden': false,
  'removed': false,
  'sent_at': '2026-11-26T10:00:00Z',
};

Future<FakeAdapter> start(WidgetTester tester, Map<String, Object?> sent, {bool windowOpen = true}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({'aionex.locale': 'en'});
  final preferences = await SharedPreferences.getInstance();
  final store = MemorySessionStore(refreshToken: 'saved');
  var messages = <Object>[inbound];
  final adapter = FakeAdapter((request) async {
    final path = request.uri.path.replaceFirst('/api/v1', '');
    return switch ((request.method, path)) {
      ('POST', '/auth/refresh') => jsonBody(200, grantJson()),
      ('GET', '/auth/me') => jsonBody(200, userJson()),
      ('GET', '/social/accounts') => jsonBody(200, {'items': <Object>[]}),
      ('GET', '/social/posts') => jsonBody(200, {'items': <Object>[]}),
      ('GET', '/social/media') => jsonBody(200, {'uploads': <Object>[], 'studio': <Object>[]}),
      ('GET', '/social/inbox/status') => jsonBody(200, {
          'meta_app_configured': true,
          'webhook_configured': true,
          'webhook_url': 'x',
          'poll_enabled': true,
          'poll_seconds': 300,
          'messaging_window_hours': 24,
          'live_verified': true,
          'accounts': <Object>[],
        }),
      ('GET', '/social/inbox/conversations') => jsonBody(200, {
          'items': [conversation(windowOpen: windowOpen)],
          'unread_conversations': 1,
          'has_more': false,
        }),
      ('GET', '/social/inbox/conversations/c1') => jsonBody(200, conversation(windowOpen: windowOpen, messages: messages)),
      ('PATCH', '/social/inbox/conversations/c1') => () {
          sent['patch'] = body(request);
          return jsonBody(200, conversation(unread: 0, messages: messages));
        }(),
      ('POST', '/social/inbox/conversations/c1/suggest') => () {
          sent['suggest'] = body(request);
          return jsonBody(200, {'reply': 'Yes, we ship to Dubai.', 'language': 'en', 'model': 'm', 'provider': 'p', 'aionex_ai': true});
        }(),
      ('POST', '/social/inbox/conversations/c1/reply') => () {
          sent['reply'] = body(request);
          messages = [
            inbound,
            {...inbound, 'id': 'm2', 'direction': 'outbound', 'author_name': null, 'body': 'Yes, we ship to Dubai.'},
          ];
          return jsonBody(200, conversation(unread: 0, messages: messages));
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
  container.read(routerProvider).go('/social');
  await tester.pumpAndSettle();
  await tester.tap(find.text('Unified inbox'));
  await tester.pumpAndSettle();
  return adapter;
}

void main() {
  testWidgets('a DM is opened, marked read, answered with an AI suggestion', (tester) async {
    final sent = <String, Object?>{};
    await start(tester, sent);
    expect(find.text('Sara'), findsOneWidget);
    await tester.tap(find.byKey(const Key('inbox-c1')));
    await tester.pumpAndSettle();
    // Customer text is shown as plain text, markup and all.
    expect(find.text('<b>Do you ship to Dubai?</b>'), findsOneWidget);
    expect(sent['patch'], {'read': true});

    await tester.tap(find.byKey(const Key('inbox-suggest')));
    await tester.pumpAndSettle();
    expect((sent['suggest']! as Map)['language'], 'en');
    expect(find.text('This is only a suggestion. Review and edit it before sending.'), findsOneWidget);
    tester.state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first).clearSnackBars();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('inbox-send')));
    await tester.pumpAndSettle();
    expect(sent['reply'], {'text': 'Yes, we ship to Dubai.'});
    expect(find.text('Your reply'), findsOneWidget);
  });

  testWidgets('a DM past the 24-hour window cannot be answered', (tester) async {
    await start(tester, {}, windowOpen: false);
    await tester.tap(find.byKey(const Key('inbox-c1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('inbox-window-closed')), findsOneWidget);
    expect(find.byKey(const Key('inbox-reply')), findsNothing);
  });
}
