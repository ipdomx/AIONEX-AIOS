import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart' show DateFormat;

import '../../../l10n/generated/app_localizations.dart';
import '../../core/auth/session_controller.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../auth/password_recovery_pages.dart';
import '../workspace/workspace_models.dart';
import '../workspace/workspace_repository.dart';

const supportCategories = ['general', 'technical', 'billing', 'security', 'account', 'project'];
const supportPriorities = ['low', 'normal', 'high', 'urgent'];

String supportCategoryLabel(AppLocalizations l, String value) => switch (value) {
      'technical' => l.support_category_technical,
      'billing' => l.support_category_billing,
      'security' => l.support_category_security,
      'account' => l.support_category_account,
      'project' => l.support_category_project,
      _ => l.support_category_general,
    };

String supportPriorityLabel(AppLocalizations l, String value) => switch (value) {
      'low' => l.support_priority_low,
      'high' => l.support_priority_high,
      'urgent' => l.support_priority_urgent,
      _ => l.support_priority_normal,
    };

final _ticketProvider = FutureProvider.autoDispose.family<SupportTicket, String>(
  (ref, id) => ref.watch(workspaceRepositoryProvider).ticket(id),
);

class SupportPage extends ConsumerWidget {
  const SupportPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final tickets = ref.watch(ticketsProvider);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    return Scaffold(
      appBar: AppBar(
        title: Text(l.support_title),
        actions: [
          IconButton(
            tooltip: l.support_refresh,
            onPressed: () => ref.invalidate(ticketsProvider),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('new-ticket'),
        onPressed: () => showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          showDragHandle: true,
          builder: (_) => const _NewTicketSheet(),
        ),
        icon: const Icon(Icons.add),
        label: Text(l.support_newTicket),
      ),
      body: AsyncView(
        value: tickets,
        onRetry: () => ref.invalidate(ticketsProvider),
        builder: (items) => items.isEmpty
            ? ListView(children: [EmptyState(icon: Icons.support_agent, title: l.support_empty)])
            : RefreshIndicator(
                onRefresh: () => ref.refresh(ticketsProvider.future),
                child: ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                  itemCount: items.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final ticket = items[index];
                    return Card(
                      child: ListTile(
                        key: Key('ticket-${ticket.id}'),
                        title: Text(ticket.subject),
                        subtitle: Text([
                          supportCategoryLabel(l, ticket.category),
                          supportPriorityLabel(l, ticket.priority),
                          if (ticket.lastMessageAt != null) format.format(ticket.lastMessageAt!.toLocal()),
                        ].join(' · ')),
                        trailing: StatusChip(
                          label: ticket.status,
                          positive: ticket.status == 'resolved' || ticket.status == 'closed',
                        ),
                        onTap: () => context.go('/support/${Uri.encodeComponent(ticket.id)}'),
                      ),
                    );
                  },
                ),
              ),
      ),
    );
  }
}

class _NewTicketSheet extends ConsumerStatefulWidget {
  const _NewTicketSheet();

  @override
  ConsumerState<_NewTicketSheet> createState() => _NewTicketSheetState();
}

class _NewTicketSheetState extends ConsumerState<_NewTicketSheet> {
  final _formKey = GlobalKey<FormState>();
  final _subject = TextEditingController();
  final _message = TextEditingController();
  String _category = 'general';
  String _priority = 'normal';
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _subject.dispose();
    _message.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    if (_busy || !(_formKey.currentState?.validate() ?? false)) return;
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final ticket = await ref.read(workspaceRepositoryProvider).createTicket(
            subject: _subject.text,
            message: _message.text,
            category: _category,
            priority: _priority,
          );
      ref.invalidate(ticketsProvider);
      if (!mounted) return;
      Navigator.of(context).pop();
      GoRouter.of(context).go('/support/${Uri.encodeComponent(ticket.id)}');
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(l, error, l.support_saveError));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.viewInsetsOf(context).bottom + 20),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(l.support_newTicket, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 16),
              TextFormField(
                key: const Key('ticket-subject'),
                controller: _subject,
                enabled: !_busy,
                maxLength: 240,
                decoration: InputDecoration(labelText: l.support_subject),
                validator: (value) => (value?.trim().length ?? 0) >= 3 ? null : l.support_subject,
              ),
              Row(
                children: [
                  Expanded(
                    child: DropdownButtonFormField<String>(
                      initialValue: _category,
                      items: [
                        for (final value in supportCategories)
                          DropdownMenuItem(value: value, child: Text(supportCategoryLabel(l, value))),
                      ],
                      onChanged: _busy ? null : (value) => setState(() => _category = value ?? 'general'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: DropdownButtonFormField<String>(
                      initialValue: _priority,
                      items: [
                        for (final value in supportPriorities)
                          DropdownMenuItem(value: value, child: Text(supportPriorityLabel(l, value))),
                      ],
                      onChanged: _busy ? null : (value) => setState(() => _priority = value ?? 'normal'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextFormField(
                key: const Key('ticket-message'),
                controller: _message,
                enabled: !_busy,
                minLines: 4,
                maxLines: 8,
                maxLength: 10000,
                decoration: InputDecoration(labelText: l.support_message, alignLabelWithHint: true),
                validator: (value) => (value?.trim().length ?? 0) >= 10 ? null : l.support_message,
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Notice(text: _error!, tone: NoticeTone.error),
              ],
              const SizedBox(height: 12),
              FilledButton(
                key: const Key('ticket-create'),
                onPressed: _busy ? null : _create,
                child: Text(l.support_create),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class SupportTicketPage extends ConsumerStatefulWidget {
  const SupportTicketPage({super.key, required this.ticketId});

  final String ticketId;

  @override
  ConsumerState<SupportTicketPage> createState() => _SupportTicketPageState();
}

class _SupportTicketPageState extends ConsumerState<SupportTicketPage> {
  final _reply = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _reply.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final l = AppLocalizations.of(context);
    if (_busy || _reply.text.trim().isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(workspaceRepositoryProvider).replyToTicket(widget.ticketId, _reply.text);
      _reply.clear();
      ref.invalidate(_ticketProvider(widget.ticketId));
      ref.invalidate(ticketsProvider);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.support_replySent)));
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(l, error, l.support_saveError));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final ticket = ref.watch(_ticketProvider(widget.ticketId));
    final me = switch (ref.watch(sessionProvider).value) {
      SignedIn(:final user) => user.id,
      _ => '',
    };
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    return Scaffold(
      appBar: AppBar(title: Text(ticket.value?.subject ?? l.support_title, overflow: TextOverflow.ellipsis)),
      body: AsyncView(
        value: ticket,
        onRetry: () => ref.invalidate(_ticketProvider(widget.ticketId)),
        builder: (item) => Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Text(l.support_history, style: theme.textTheme.titleMedium),
                  const SizedBox(height: 10),
                  for (final message in item.messages)
                    Align(
                      alignment: message.senderId == me ? AlignmentDirectional.centerEnd : AlignmentDirectional.centerStart,
                      child: Card(
                        color: message.senderId == me ? theme.colorScheme.primaryContainer : null,
                        margin: const EdgeInsets.only(bottom: 10),
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              SelectableText(message.message),
                              if (message.createdAt != null) ...[
                                const SizedBox(height: 4),
                                Text(format.format(message.createdAt!.toLocal()), style: theme.textTheme.labelSmall),
                              ],
                            ],
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            if (_error != null)
              Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: Notice(text: _error!, tone: NoticeTone.error)),
            if (item.status != 'closed')
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Expanded(
                        child: TextField(
                          key: const Key('ticket-reply'),
                          controller: _reply,
                          enabled: !_busy,
                          minLines: 1,
                          maxLines: 5,
                          maxLength: 10000,
                          decoration: InputDecoration(labelText: l.support_replyPlaceholder, counterText: ''),
                        ),
                      ),
                      const SizedBox(width: 8),
                      IconButton.filled(
                        key: const Key('ticket-send'),
                        tooltip: l.support_sendReply,
                        onPressed: _busy || _reply.text.trim().isEmpty ? null : _send,
                        icon: const Icon(Icons.send),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
