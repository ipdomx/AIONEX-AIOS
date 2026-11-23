import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../auth/password_recovery_pages.dart';
import '../workspace/workspace_models.dart';
import '../workspace/workspace_repository.dart';

String conversationStatusLabel(AppLocalizations l, String status) => switch (status) {
      'open' => l.conversations_status_open,
      'paused' => l.conversations_status_paused,
      'closed' => l.conversations_status_closed,
      'expired' => l.conversations_status_expired,
      'queued' => l.conversations_status_queued,
      'running' => l.conversations_status_running,
      'completed' => l.conversations_status_completed,
      'failed' => l.conversations_status_failed,
      'cancelled' => l.conversations_status_cancelled,
      'needs_review' => l.conversations_status_needs_review,
      _ => status,
    };

/// Project conversations: durable, owner-limited threads with the configured assistant.
class ConversationsPage extends ConsumerWidget {
  const ConversationsPage({super.key, this.projectId});

  /// Pre-selects the project when opened from a project card.
  final String? projectId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final conversations = ref.watch(conversationsProvider);
    final projects = ref.watch(projectsProvider);
    final names = {for (final project in projects.value ?? const <Project>[]) project.id: project.name};
    return Scaffold(
      appBar: AppBar(
        title: Text(l.conversations_title),
        actions: [
          IconButton(
            tooltip: l.conversations_refresh,
            onPressed: () => ref.invalidate(conversationsProvider),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('new-conversation'),
        onPressed: () => showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          showDragHandle: true,
          builder: (_) => _NewConversationSheet(projectId: projectId),
        ),
        icon: const Icon(Icons.add_comment_outlined),
        label: Text(l.conversations_new),
      ),
      body: AsyncView(
        value: conversations,
        onRetry: () => ref.invalidate(conversationsProvider),
        builder: (items) {
          final visible = projectId == null ? items : items.where((c) => c.projectId == projectId).toList();
          if (visible.isEmpty) {
            return ListView(children: [EmptyState(icon: Icons.forum_outlined, title: l.conversations_empty)]);
          }
          return RefreshIndicator(
            onRefresh: () => ref.refresh(conversationsProvider.future),
            child: ListView.separated(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
              itemCount: visible.length,
              separatorBuilder: (_, _) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final item = visible[index];
                return Card(
                  child: ListTile(
                    key: Key('conversation-${item.id}'),
                    title: Text(item.title),
                    subtitle: Text(
                      [
                        if (names[item.projectId] != null) names[item.projectId]!,
                        '${item.messagesUsed}/${item.messagesAllowed}',
                      ].join(' · '),
                    ),
                    trailing: StatusChip(label: conversationStatusLabel(l, item.status), positive: item.isOpen),
                    onTap: () => context.go('/conversations/${Uri.encodeComponent(item.id)}'),
                  ),
                );
              },
            ),
          );
        },
      ),
    );
  }
}

class _NewConversationSheet extends ConsumerStatefulWidget {
  const _NewConversationSheet({this.projectId});

  final String? projectId;

  @override
  ConsumerState<_NewConversationSheet> createState() => _NewConversationSheetState();
}

class _NewConversationSheetState extends ConsumerState<_NewConversationSheet> {
  final _title = TextEditingController();
  String? _projectId;
  bool _busy = false;
  String? _error;

  /// Kept across retries of the same attempt so the server never opens two threads.
  String? _requestId;

  @override
  void initState() {
    super.initState();
    _projectId = widget.projectId;
    _title.addListener(() => setState(() => _requestId = null));
  }

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    final l = AppLocalizations.of(context);
    final projectId = _projectId;
    if (_busy || projectId == null || _title.text.trim().isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    _requestId ??= newRequestId();
    try {
      final created = await ref.read(workspaceRepositoryProvider).createConversation(projectId, _title.text, _requestId!);
      ref.invalidate(conversationsProvider);
      if (!mounted) return;
      Navigator.of(context).pop();
      GoRouter.of(context).go('/conversations/${Uri.encodeComponent(created.id)}');
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(l, error, l.conversations_error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final projects = ref.watch(projectsProvider);
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.viewInsetsOf(context).bottom + 20),
      child: AsyncView(
        value: projects,
        onRetry: () => ref.invalidate(projectsProvider),
        builder: (items) {
          final active = items.where((p) => p.isActive).toList();
          if (active.isEmpty) {
            return Padding(padding: const EdgeInsets.all(12), child: Notice(text: l.dashboard_noProjectsCopy));
          }
          if (_projectId == null || !active.any((p) => p.id == _projectId)) _projectId = active.first.id;
          return Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(l.conversations_new, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                initialValue: _projectId,
                decoration: InputDecoration(labelText: l.conversations_project),
                items: [for (final project in active) DropdownMenuItem(value: project.id, child: Text(project.name))],
                onChanged: _busy
                    ? null
                    : (value) => setState(() {
                          _projectId = value;
                          _requestId = null;
                        }),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('conversation-title'),
                controller: _title,
                enabled: !_busy,
                maxLength: 240,
                decoration: InputDecoration(labelText: l.conversations_name),
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Notice(text: _error!, tone: NoticeTone.error),
              ],
              const SizedBox(height: 12),
              FilledButton(
                key: const Key('conversation-create'),
                onPressed: _busy || _title.text.trim().isEmpty ? null : _create,
                child: Text(l.conversations_new),
              ),
            ],
          );
        },
      ),
    );
  }
}
