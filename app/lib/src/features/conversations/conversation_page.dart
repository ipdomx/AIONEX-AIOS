import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_exception.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../auth/password_recovery_pages.dart';
import '../workspace/workspace_models.dart';
import '../workspace/workspace_repository.dart';
import 'conversations_page.dart';

/// One conversation. The assistant answers through a durable server job, so the
/// screen polls every 3 s (as the website does) and never resends on its own.
class ConversationPage extends ConsumerStatefulWidget {
  const ConversationPage({super.key, required this.conversationId, this.pollInterval = const Duration(seconds: 3)});

  final String conversationId;
  final Duration pollInterval;

  @override
  ConsumerState<ConversationPage> createState() => _ConversationPageState();
}

class _ConversationPageState extends ConsumerState<ConversationPage> {
  final _message = TextEditingController();
  final _scroll = ScrollController();
  ConversationHistory? _history;
  ConversationPolicy? _policy;
  List<ConversationAgent> _agents = const [];
  String? _agentId;
  bool _external = false;
  bool _busy = false;
  bool _loading = true;
  int _syncFailures = 0;
  String? _error;
  Timer? _timer;
  bool _polling = false;

  /// Same id for retries of the same text, so a lost reply never sends twice.
  String? _sendRequestId;

  WorkspaceRepository get _repo => ref.read(workspaceRepositoryProvider);

  @override
  void initState() {
    super.initState();
    _message.addListener(() {
      _sendRequestId = null;
      setState(() {});
    });
    unawaited(_load());
    _timer = Timer.periodic(widget.pollInterval, (_) => unawaited(_poll()));
  }

  @override
  void dispose() {
    _timer?.cancel();
    _message.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait<Object>([
        _repo.history(widget.conversationId),
        _repo.conversationPolicy(),
        _repo.agents(),
      ]);
      if (!mounted) return;
      final agents = results[2] as List<ConversationAgent>;
      setState(() {
        _history = results[0] as ConversationHistory;
        _policy = results[1] as ConversationPolicy;
        _agents = agents;
        _agentId = agents.any((a) => a.id == _agentId) ? _agentId : agents.firstOrNull?.id;
        _error = null;
      });
      _scrollToEnd();
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(AppLocalizations.of(context), error, AppLocalizations.of(context).conversations_error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _poll() async {
    if (_polling || _loading || !mounted) return;
    _polling = true;
    try {
      final next = await _repo.history(widget.conversationId);
      if (!mounted) return;
      final grew = (next.turns.lastOrNull?.assistantMessage ?? '') != (_history?.turns.lastOrNull?.assistantMessage ?? '') ||
          next.turns.length != (_history?.turns.length ?? 0);
      setState(() {
        _history = next;
        _syncFailures = 0;
      });
      if (grew) _scrollToEnd();
    } on Object {
      if (mounted) setState(() => _syncFailures++);
    } finally {
      _polling = false;
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        unawaited(_scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 250), curve: Curves.easeOut));
      }
    });
  }

  Future<void> _send() async {
    final l = AppLocalizations.of(context);
    final text = _message.text.trim();
    final agentId = _agentId;
    if (_busy || text.isEmpty || agentId == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final requestId = _sendRequestId ??= newRequestId();
    try {
      await _repo.sendMessage(
        widget.conversationId,
        message: text,
        agentId: agentId,
        requestId: requestId,
        confirmExternalProcessing: _external,
      );
      _message.clear();
      _sendRequestId = null;
      await _poll();
      _policy = await _repo.conversationPolicy();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = error.failure == ApiFailure.network ? l.conversations_reconnecting : error.message);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _close() async {
    final l = AppLocalizations.of(context);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        content: Text(l.conversations_closeConfirm),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(l.projects_cancel)),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(l.conversations_close)),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _repo.closeConversation(widget.conversationId);
      ref.invalidate(conversationsProvider);
      await _poll();
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(l, error, l.conversations_error));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final history = _history;
    final conversation = history?.conversation;
    final open = conversation?.isOpen ?? false;
    final agent = _agents.where((a) => a.id == _agentId).firstOrNull;
    final maxChars = _policy?.maxMessageCharacters ?? 4000;
    final canSend = open &&
        !_busy &&
        agent != null &&
        _message.text.trim().isNotEmpty &&
        _message.text.length <= maxChars &&
        (!agent.externalProcessing || _external) &&
        !(history?.waiting ?? false);
    return Scaffold(
      appBar: AppBar(
        title: Text(conversation?.title ?? l.conversations_title, overflow: TextOverflow.ellipsis),
        actions: [
          if (open)
            IconButton(
              key: const Key('conversation-close'),
              tooltip: l.conversations_close,
              onPressed: _close,
              icon: const Icon(Icons.lock_outline),
            ),
        ],
      ),
      body: _loading
          ? Center(child: Semantics(label: l.conversations_loading, child: const CircularProgressIndicator()))
          : history == null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(_error ?? l.conversations_error, textAlign: TextAlign.center),
                      const SizedBox(height: 12),
                      FilledButton(onPressed: () {
                        setState(() => _loading = true);
                        unawaited(_load());
                      }, child: Text(l.app_retry)),
                    ]),
                  ),
                )
              : Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                      child: Row(
                        children: [
                          StatusChip(label: conversationStatusLabel(l, conversation!.status), positive: open),
                          const SizedBox(width: 8),
                          Text('${conversation.messagesUsed}/${conversation.messagesAllowed}',
                              style: theme.textTheme.bodySmall),
                        ],
                      ),
                    ),
                    if (_syncFailures > 1)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                        child: Notice(text: l.conversations_reconnecting),
                      ),
                    Expanded(
                      child: history.turns.isEmpty
                          ? EmptyState(icon: Icons.chat_outlined, title: l.conversations_firstMessage)
                          : ListView.builder(
                              controller: _scroll,
                              padding: const EdgeInsets.all(16),
                              itemCount: history.turns.length,
                              itemBuilder: (context, index) => _Turn(turn: history.turns[index]),
                            ),
                    ),
                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        child: Notice(key: const Key('conversation-error'), text: _error!, tone: NoticeTone.error),
                      ),
                    if (!open)
                      Padding(padding: const EdgeInsets.all(16), child: Notice(text: l.conversations_inactive))
                    else if (_agents.isEmpty)
                      Padding(padding: const EdgeInsets.all(16), child: Notice(text: l.conversations_notConfigured))
                    else
                      SafeArea(
                        top: false,
                        child: Padding(
                          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (_agents.length > 1)
                                DropdownButtonFormField<String>(
                                  initialValue: _agentId,
                                  isDense: true,
                                  decoration: InputDecoration(labelText: l.conversations_chooseAssistant),
                                  items: [for (final a in _agents) DropdownMenuItem(value: a.id, child: Text(a.name))],
                                  onChanged: (value) => setState(() => _agentId = value),
                                ),
                              if (agent?.externalProcessing ?? false)
                                CheckboxListTile(
                                  key: const Key('external-consent'),
                                  dense: true,
                                  contentPadding: EdgeInsets.zero,
                                  value: _external,
                                  onChanged: (value) => setState(() => _external = value ?? false),
                                  title: Text(l.conversations_externalConsent, style: theme.textTheme.bodySmall),
                                ),
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  Expanded(
                                    child: TextField(
                                      key: const Key('conversation-message'),
                                      controller: _message,
                                      minLines: 1,
                                      maxLines: 5,
                                      maxLength: maxChars,
                                      enabled: !_busy,
                                      decoration: InputDecoration(labelText: l.conversations_message, counterText: ''),
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  IconButton.filled(
                                    key: const Key('conversation-send'),
                                    tooltip: _busy ? l.conversations_sending : l.conversations_send,
                                    onPressed: canSend ? _send : null,
                                    icon: const Icon(Icons.send),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ),
                  ],
                ),
    );
  }
}

class _Turn extends StatelessWidget {
  const _Turn({required this.turn});

  final ConversationTurn turn;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final answer = turn.assistantMessage;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Align(
            alignment: AlignmentDirectional.centerEnd,
            child: _Bubble(
              label: l.conversations_you,
              text: turn.userMessage,
              color: theme.colorScheme.primaryContainer,
            ),
          ),
          const SizedBox(height: 6),
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: turn.isPending
                ? _Bubble(
                    label: l.conversations_assistant,
                    text: turn.status == 'running' ? l.conversations_working : l.conversations_pending,
                    color: theme.colorScheme.surfaceContainerHigh,
                    busy: true,
                  )
                : turn.status == 'needs_review'
                    ? _Bubble(label: l.conversations_assistant, text: l.conversations_review, color: theme.colorScheme.surfaceContainerHigh)
                    : _Bubble(
                        label: l.conversations_assistant,
                        text: answer ?? turn.error ?? conversationStatusLabel(l, turn.status),
                        color: theme.colorScheme.surfaceContainerHigh,
                        selectable: true,
                      ),
          ),
        ],
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.label, required this.text, required this.color, this.busy = false, this.selectable = false});

  final String label;
  final String text;
  final Color color;
  final bool busy;
  final bool selectable;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ConstrainedBox(
      constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.86),
      child: DecoratedBox(
        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(14)),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
              const SizedBox(height: 4),
              if (busy)
                Row(mainAxisSize: MainAxisSize.min, children: [
                  const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
                  const SizedBox(width: 8),
                  Flexible(child: Text(text)),
                ])
              else if (selectable)
                SelectableText(text)
              else
                Text(text),
            ],
          ),
        ),
      ),
    );
  }
}
