import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart' show DateFormat;

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/providers.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;
DateTime? _d(Object? v) => v is String ? DateTime.tryParse(v) : null;
List<Map<String, Object?>> _rows(Object? v) =>
    v is List ? [for (final r in v) if (r is Map) r.cast<String, Object?>()] : const [];

const replyMax = 2000;

@immutable
class InboxAccount {
  const InboxAccount({required this.id, required this.name, required this.state, required this.missingScopes, required this.subscribedAt});
  final String id;
  final String name;
  final String state;
  final List<String> missingScopes;
  final DateTime? subscribedAt;
}

@immutable
class InboxReadiness {
  const InboxReadiness({required this.metaConfigured, required this.webhookConfigured, required this.pollMinutes, required this.liveVerified, required this.accounts});
  final bool metaConfigured;
  final bool webhookConfigured;
  final int pollMinutes;
  final bool liveVerified;
  final List<InboxAccount> accounts;

  factory InboxReadiness.fromJson(Map<String, Object?> j) => InboxReadiness(
        metaConfigured: j['meta_app_configured'] == true,
        webhookConfigured: j['webhook_configured'] == true,
        pollMinutes: (_i(j['poll_seconds']) / 60).ceil(),
        liveVerified: j['live_verified'] == true,
        accounts: [
          for (final a in _rows(j['accounts']))
            InboxAccount(
              id: _s(a['account_id']),
              name: _s(a['display_name']),
              state: _s(a['state']),
              missingScopes: a['missing_scopes'] is List ? (a['missing_scopes']! as List).whereType<String>().toList() : const [],
              subscribedAt: _d(a['webhook_subscribed_at']),
            ),
        ],
      );
}

@immutable
class InboxMessage {
  const InboxMessage({
    required this.id,
    required this.inbound,
    required this.kind,
    required this.author,
    required this.body,
    required this.attachments,
    required this.hidden,
    required this.removed,
    required this.sentAt,
  });
  final String id;
  final bool inbound;
  final String kind;
  final String? author;
  final String body;
  final List<String> attachments;
  final bool hidden;
  final bool removed;
  final DateTime? sentAt;
}

@immutable
class InboxConversation {
  const InboxConversation({
    required this.id,
    required this.accountName,
    required this.accountStatus,
    required this.provider,
    required this.channel,
    required this.participant,
    required this.status,
    required this.unread,
    required this.lastMessageAt,
    required this.preview,
    required this.windowApplies,
    required this.windowOpen,
    required this.windowExpiresAt,
    required this.messages,
  });

  final String id;
  final String accountName;
  final String accountStatus;
  final String provider;
  final String channel;
  final String? participant;
  final String status;
  final int unread;
  final DateTime? lastMessageAt;
  final String preview;
  final bool windowApplies;
  final bool windowOpen;
  final DateTime? windowExpiresAt;
  final List<InboxMessage> messages;

  bool get canReply => accountStatus != 'revoked' && (!windowApplies || windowOpen);

  factory InboxConversation.fromJson(Map<String, Object?> j) {
    final window = j['reply_window'] is Map ? (j['reply_window']! as Map).cast<String, Object?>() : const <String, Object?>{};
    return InboxConversation(
      id: _s(j['id']),
      accountName: _s(j['account_name']),
      accountStatus: _s(j['account_status']),
      provider: _s(j['provider']),
      channel: _s(j['channel']),
      participant: j['participant_name'] as String?,
      status: _s(j['status'], 'open'),
      unread: _i(j['unread_count']),
      lastMessageAt: _d(j['last_message_at']),
      preview: _s(j['last_message_preview']),
      windowApplies: window['applies'] == true,
      windowOpen: window['open'] == true,
      windowExpiresAt: _d(window['expires_at']),
      messages: [
        for (final m in _rows(j['messages']))
          InboxMessage(
            id: _s(m['id']),
            inbound: m['direction'] == 'inbound',
            kind: _s(m['kind']),
            author: m['author_name'] as String?,
            body: _s(m['body']),
            attachments: [for (final a in _rows(m['attachments'])) _s(a['type'], 'file')],
            hidden: m['hidden'] == true,
            removed: m['removed'] == true,
            sentAt: _d(m['sent_at']),
          ),
      ],
    );
  }
}

@immutable
class InboxFilter {
  const InboxFilter({this.platform, this.unreadOnly = false, this.status});
  final String? platform;
  final bool unreadOnly;
  final String? status;

  Map<String, Object?> get query => {'platform': ?platform, if (unreadOnly) 'unread': 'true', 'status': ?status};

  @override
  bool operator ==(Object other) =>
      other is InboxFilter && other.platform == platform && other.unreadOnly == unreadOnly && other.status == status;

  @override
  int get hashCode => Object.hash(platform, unreadOnly, status);
}

/// The unified inbox, the same endpoints as the website's social-inbox-client.
class SocialInboxRepository {
  SocialInboxRepository(this._api);
  final ApiClient _api;

  String _c(String id) => '/social/inbox/conversations/${Uri.encodeComponent(id)}';

  Future<InboxReadiness> status() async => InboxReadiness.fromJson(await _api.getJson('/social/inbox/status'));

  Future<void> subscribe(String accountId) async =>
      _api.postJson('/social/inbox/accounts/${Uri.encodeComponent(accountId)}/subscribe', retry: false);

  Future<({List<InboxConversation> items, int unread})> conversations(InboxFilter filter) async {
    final json = await _api.getJson('/social/inbox/conversations', query: filter.query);
    return (items: [for (final r in _rows(json['items'])) InboxConversation.fromJson(r)], unread: _i(json['unread_conversations']));
  }

  Future<InboxConversation> thread(String id) async => InboxConversation.fromJson(await _api.getJson(_c(id)));

  Future<InboxConversation> update(String id, {bool? read, String? status}) async =>
      InboxConversation.fromJson(await _api.patchJson(_c(id), body: {'read': ?read, 'status': ?status}));

  Future<InboxConversation> reply(String id, String text) async =>
      InboxConversation.fromJson(await _api.postJson('${_c(id)}/reply', body: {'text': text.trim()}, retry: false));

  Future<String> suggest(String id, {required String language}) async {
    final json = await _api.postJson('${_c(id)}/suggest', body: {'language': language, 'tone': 'friendly'}, retry: false);
    return _s(json['reply']);
  }

  Future<InboxConversation> setHidden(String messageId, bool hidden) async => InboxConversation.fromJson(
        await _api.postJson('/social/inbox/messages/${Uri.encodeComponent(messageId)}/visibility', body: {'hidden': hidden}, retry: false),
      );
}

final socialInboxRepositoryProvider = Provider<SocialInboxRepository>((ref) => SocialInboxRepository(ref.watch(apiClientProvider)));
final inboxStatusProvider = FutureProvider.autoDispose<InboxReadiness>((ref) => ref.watch(socialInboxRepositoryProvider).status());
final inboxConversationsProvider = FutureProvider.autoDispose.family<({List<InboxConversation> items, int unread}), InboxFilter>(
  (ref, filter) => ref.watch(socialInboxRepositoryProvider).conversations(filter),
);
final inboxThreadProvider =
    FutureProvider.autoDispose.family<InboxConversation, String>((ref, id) => ref.watch(socialInboxRepositoryProvider).thread(id));

String inboxError(AppLocalizations l, Object error) {
  if (error is! ApiException) return l.socialInbox_errors_generic;
  final code = error.code ?? '';
  if (code == 'DAILY_MESSAGE_LIMIT' || code == 'MESSAGE_CREDITS_EXHAUSTED') return l.socialInbox_errors_aiQuota;
  if (error.statusCode == 429) return l.socialInbox_errors_rateLimited;
  return switch (code) {
    'messaging-window-closed' => l.socialInbox_errors_windowClosed,
    'account-reconnect-required' => l.socialInbox_errors_reconnect,
    'account-disconnected' => l.socialInbox_errors_disconnected,
    'meta-permission-required' => l.socialInbox_errors_permission,
    'provider-not-configured' => l.socialInbox_errors_notConfigured,
    'reply-outcome-unknown' => l.socialInbox_errors_outcomeUnknown,
    'ai-nothing-to-answer' => l.socialInbox_errors_aiNothing,
    'ai-assistant-unavailable' => l.socialInbox_errors_aiUnavailable,
    _ when code.startsWith('ai-') => l.socialInbox_errors_aiFailed,
    _ when error.statusCode == 404 => l.socialInbox_errors_notFound,
    _ => l.socialInbox_errors_generic,
  };
}

String inboxStatusLabel(AppLocalizations l, String s) => switch (s) {
      'pending' => l.socialInbox_statuses_pending,
      'closed' => l.socialInbox_statuses_closed,
      _ => l.socialInbox_statuses_open,
    };

/// The inbox tab: readiness, filters and the conversation list.
class InboxTab extends ConsumerStatefulWidget {
  const InboxTab({super.key});

  @override
  ConsumerState<InboxTab> createState() => _InboxTabState();
}

class _InboxTabState extends ConsumerState<InboxTab> {
  InboxFilter _filter = const InboxFilter();

  Future<void> _subscribe(String accountId) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(socialInboxRepositoryProvider).subscribe(accountId);
      messenger.showSnackBar(SnackBar(content: Text(l.socialInbox_readiness_subscribed)));
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(inboxError(l, error))));
    }
    ref.invalidate(inboxStatusProvider);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    final readiness = ref.watch(inboxStatusProvider);
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(inboxStatusProvider);
        ref.invalidate(inboxConversationsProvider(_filter));
      },
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(l.socialInbox_description, style: theme.textTheme.bodySmall),
          const SizedBox(height: 8),
          readiness.when(
            loading: () => const LinearProgressIndicator(),
            error: (e, _) => Notice(text: inboxError(l, e), tone: NoticeTone.error),
            data: (r) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (!r.metaConfigured) Notice(text: l.socialInbox_readiness_notConfigured, tone: NoticeTone.error),
              if (r.metaConfigured && r.accounts.any((a) => a.state == 'awaiting_permission'))
                Notice(key: const Key('inbox-awaiting'), text: '${l.socialInbox_readiness_awaitingTitle}. ${l.socialInbox_readiness_awaitingBody}'),
              if (!r.webhookConfigured) Text(l.socialInbox_readiness_webhookMissing, style: theme.textTheme.bodySmall),
              if (!r.liveVerified) Text(l.socialInbox_readiness_liveNotVerified(r.pollMinutes), style: theme.textTheme.bodySmall),
              for (final a in r.accounts)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(a.name),
                  subtitle: Text([
                    switch (a.state) {
                      'ready' => l.socialInbox_readiness_states_ready,
                      'awaiting_permission' => l.socialInbox_readiness_states_awaiting_permission,
                      'reconnect_required' => l.socialInbox_readiness_states_reconnect_required,
                      _ => l.socialInbox_readiness_states_disconnected,
                    },
                    if (a.missingScopes.isNotEmpty) l.socialInbox_readiness_missingScopes(a.missingScopes.join(', ')),
                    if (a.subscribedAt != null) l.socialInbox_readiness_subscribedAt(format.format(a.subscribedAt!.toLocal())),
                  ].join(' · ')),
                  trailing: a.state == 'ready' && a.subscribedAt == null
                      ? TextButton(onPressed: () => _subscribe(a.id), child: Text(l.socialInbox_readiness_subscribe))
                      : null,
                ),
            ]),
          ),
          const SizedBox(height: 8),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final p in [null, 'facebook', 'instagram'])
              ChoiceChip(
                label: Text(switch (p) { 'facebook' => l.socialInbox_filters_facebook, 'instagram' => l.socialInbox_filters_instagram, _ => l.socialInbox_filters_all }),
                selected: _filter.platform == p,
                onSelected: (_) => setState(() => _filter = InboxFilter(platform: p, unreadOnly: _filter.unreadOnly, status: _filter.status)),
              ),
            FilterChip(
              key: const Key('inbox-unread'),
              label: Text(l.socialInbox_filters_unreadOnly),
              selected: _filter.unreadOnly,
              onSelected: (v) => setState(() => _filter = InboxFilter(platform: _filter.platform, unreadOnly: v, status: _filter.status)),
            ),
          ]),
          const SizedBox(height: 8),
          AsyncView(
            value: ref.watch(inboxConversationsProvider(_filter)),
            onRetry: () => ref.invalidate(inboxConversationsProvider(_filter)),
            builder: (page) => page.items.isEmpty
                ? Text(_filter == const InboxFilter() ? l.socialInbox_list_empty : l.socialInbox_list_emptyFiltered,
                    style: theme.textTheme.bodySmall)
                : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    Text(l.socialInbox_list_unread(page.unread), style: theme.textTheme.bodySmall),
                    for (final c in page.items)
                      Card(
                        key: Key('inbox-${c.id}'),
                        child: ListTile(
                          leading: Badge(
                            isLabelVisible: c.unread > 0,
                            label: Text('${c.unread}'),
                            child: Icon(c.channel == 'dm' ? Icons.mail_outline : Icons.comment_outlined),
                          ),
                          title: Text(c.participant ?? l.socialInbox_common_unknownParticipant),
                          subtitle: Text(
                            '${c.provider} · ${c.channel == 'dm' ? l.socialInbox_channels_dm : l.socialInbox_channels_comment} · '
                            '${inboxStatusLabel(l, c.status)}\n${c.preview}',
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                          ),
                          onTap: () async {
                            await context.push('/social/inbox/${Uri.encodeComponent(c.id)}');
                            ref.invalidate(inboxConversationsProvider(_filter));
                          },
                        ),
                      ),
                  ]),
          ),
        ],
      ),
    );
  }
}

/// One conversation: messages, hide comments, status, reply and an AI suggestion.
class InboxThreadPage extends ConsumerStatefulWidget {
  const InboxThreadPage({super.key, required this.conversationId});
  final String conversationId;

  @override
  ConsumerState<InboxThreadPage> createState() => _InboxThreadPageState();
}

class _InboxThreadPageState extends ConsumerState<InboxThreadPage> {
  final _reply = TextEditingController();
  bool _busy = false;
  bool _suggested = false;
  bool _markedRead = false;

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  SocialInboxRepository get _repo => ref.read(socialInboxRepositoryProvider);

  Future<void> _run(Future<void> Function() action, {String? done}) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      await action();
      if (done != null) messenger.showSnackBar(SnackBar(content: Text(done)));
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(inboxError(l, error))));
    } finally {
      if (mounted) setState(() => _busy = false);
      ref.invalidate(inboxThreadProvider(widget.conversationId));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    final thread = ref.watch(inboxThreadProvider(widget.conversationId));
    final c = thread.value;
    // Opening a conversation marks it read once, like the website.
    if (c != null && c.unread > 0 && !_markedRead) {
      _markedRead = true;
      scheduleMicrotask(() => _repo.update(c.id, read: true).then((_) {}, onError: (Object _) {}));
    }
    return Scaffold(
      appBar: AppBar(
        title: Text(c?.participant ?? l.socialInbox_common_unknownParticipant, overflow: TextOverflow.ellipsis),
        actions: [
          if (c != null)
            PopupMenuButton<String>(
              key: const Key('thread-status'),
              tooltip: l.socialInbox_thread_statusLabel,
              onSelected: (v) => v == 'unread'
                  ? _run(() => _repo.update(c.id, read: false))
                  : _run(() => _repo.update(c.id, status: v)),
              itemBuilder: (_) => [
                for (final s in ['open', 'pending', 'closed'])
                  CheckedPopupMenuItem(value: s, checked: c.status == s, child: Text(inboxStatusLabel(l, s))),
                PopupMenuItem(value: 'unread', child: Text(l.socialInbox_thread_markUnread)),
              ],
            ),
        ],
      ),
      body: AsyncView(
        value: thread,
        onRetry: () => ref.invalidate(inboxThreadProvider(widget.conversationId)),
        builder: (c) => Column(children: [
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(l.socialInbox_thread_account(c.accountName), style: theme.textTheme.bodySmall),
                const SizedBox(height: 8),
                for (final m in c.messages)
                  Align(
                    alignment: m.inbound ? AlignmentDirectional.centerStart : AlignmentDirectional.centerEnd,
                    child: Card(
                      key: Key('message-${m.id}'),
                      color: m.inbound ? null : theme.colorScheme.primaryContainer,
                      child: Padding(
                        padding: const EdgeInsets.all(10),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(m.inbound ? (m.author ?? l.socialInbox_common_unknownParticipant) : l.socialInbox_thread_business,
                              style: theme.textTheme.labelSmall),
                          // Text from Meta users is always shown as plain text.
                          Text(m.removed ? l.socialInbox_thread_removed : m.body),
                          for (final a in m.attachments) Text(l.socialInbox_thread_attachment(a), style: theme.textTheme.bodySmall),
                          Row(mainAxisSize: MainAxisSize.min, children: [
                            if (m.sentAt != null) Text(format.format(m.sentAt!.toLocal()), style: theme.textTheme.labelSmall),
                            if (m.hidden) ...[
                              const SizedBox(width: 6),
                              Text(l.socialInbox_thread_hidden, style: theme.textTheme.labelSmall),
                            ],
                          ]),
                          if (m.inbound && c.channel == 'comment' && !m.removed)
                            TextButton(
                              key: Key('hide-${m.id}'),
                              onPressed: _busy ? null : () => _run(() => _repo.setHidden(m.id, !m.hidden)),
                              child: Text(m.hidden ? l.socialInbox_thread_unhide : l.socialInbox_thread_hide),
                            ),
                        ]),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
              child: c.canReply
                  ? Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
                      if (c.windowApplies && c.windowExpiresAt != null)
                        Text(l.socialInbox_thread_windowOpen(format.format(c.windowExpiresAt!.toLocal())), style: theme.textTheme.bodySmall),
                      if (_suggested) Text(l.socialInbox_reply_suggestionNote, style: theme.textTheme.bodySmall),
                      TextField(
                        key: const Key('inbox-reply'),
                        controller: _reply,
                        enabled: !_busy,
                        minLines: 1,
                        maxLines: 5,
                        maxLength: replyMax,
                        decoration: InputDecoration(
                          labelText: c.channel == 'dm' ? l.socialInbox_reply_labelDm : l.socialInbox_reply_labelComment,
                          hintText: l.socialInbox_reply_placeholder,
                        ),
                        onChanged: (_) => setState(() {}),
                      ),
                      Wrap(alignment: WrapAlignment.spaceBetween, crossAxisAlignment: WrapCrossAlignment.center, spacing: 8, children: [
                        TextButton.icon(
                          key: const Key('inbox-suggest'),
                          onPressed: _busy
                              ? null
                              : () => _run(() async {
                                    final text = await _repo.suggest(c.id, language: Localizations.localeOf(context).languageCode);
                                    _reply.text = text;
                                    setState(() => _suggested = true);
                                  }),
                          icon: const Icon(Icons.auto_awesome),
                          label: Text(l.socialInbox_reply_suggest),
                        ),
                        FilledButton.icon(
                          key: const Key('inbox-send'),
                          style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
                          onPressed: _busy || _reply.text.trim().isEmpty
                              ? null
                              : () => _run(() async {
                                    await _repo.reply(c.id, _reply.text);
                                    _reply.clear();
                                    setState(() => _suggested = false);
                                  }, done: l.socialInbox_reply_sent),
                          icon: const Icon(Icons.send),
                          label: Text(l.socialInbox_reply_send),
                        ),
                      ]),
                    ])
                  : Notice(
                      key: const Key('inbox-window-closed'),
                      text: c.accountStatus == 'revoked'
                          ? l.socialInbox_errors_disconnected
                          : '${l.socialInbox_thread_windowClosedTitle} ${l.socialInbox_thread_windowClosedBody}',
                    ),
            ),
          ),
        ]),
      ),
    );
  }
}
