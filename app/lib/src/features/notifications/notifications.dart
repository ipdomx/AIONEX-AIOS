import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart' show DateFormat;

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_client.dart';
import '../../core/auth/session_controller.dart';
import '../../core/providers.dart';
import '../../widgets/async_view.dart';
import '../../widgets/error_text.dart';

@immutable
class PortalNotification {
  const PortalNotification({
    required this.id,
    required this.title,
    required this.message,
    required this.severity,
    required this.read,
    required this.createdAt,
  });

  final String id;
  final String title;
  final String message;

  /// info, success, warning or critical.
  final String severity;
  final bool read;
  final DateTime? createdAt;

  factory PortalNotification.fromJson(Map<String, Object?> json) => PortalNotification(
        id: (json['id'] as String?) ?? '',
        title: (json['title'] as String?) ?? '',
        message: (json['message'] as String?) ?? '',
        severity: (json['severity'] as String?) ?? 'info',
        read: json['read'] == true,
        createdAt: DateTime.tryParse((json['created_at'] as String?) ?? ''),
      );
}

class NotificationsRepository {
  NotificationsRepository(this._api);

  final ApiClient _api;

  Future<List<PortalNotification>> list({bool unreadOnly = false}) async {
    final json = await _api.getJson('/notifications', query: unreadOnly ? {'unread_only': 'true'} : null);
    final items = json['items'];
    return [
      if (items is List)
        for (final item in items)
          if (item is Map) PortalNotification.fromJson(item.cast<String, Object?>()),
    ];
  }

  Future<void> update(String id, {bool? read, bool? archived}) async {
    await _api.patchJson('/notifications/${Uri.encodeComponent(id)}', body: {'read': ?read, 'archived': ?archived});
  }

  Future<int> markAllRead() async {
    final json = await _api.postJson('/notifications/mark-all-read', retry: false);
    final updated = json['updated'];
    return updated is num ? updated.toInt() : 0;
  }

  /// Push: the FCM token is stored (encrypted) as a "push" endpoint of this user.
  Future<String?> registerPushToken(String token, String label) async {
    final json = await _api.postJson(
      '/communications/endpoints',
      body: {'channel': 'push', 'address': token, 'label': label},
      retry: false,
    );
    return json['id'] as String?;
  }

  Future<void> removePushEndpoint(String endpointId) async {
    await _api.deleteJson('/communications/endpoints/${Uri.encodeComponent(endpointId)}');
  }
}

final notificationsRepositoryProvider =
    Provider<NotificationsRepository>((ref) => NotificationsRepository(ref.watch(apiClientProvider)));

/// The free plan has no notifications:read, so the app neither shows the inbox nor asks for it.
final canReadNotificationsProvider = Provider.autoDispose<bool>((ref) {
  final session = ref.watch(sessionProvider).value;
  if (session is! SignedIn) return false;
  final granted = session.user.permissions;
  return granted.contains('*') || granted.contains('notifications:read');
});

final notificationsProvider = FutureProvider.autoDispose<List<PortalNotification>>(
  (ref) async => ref.watch(canReadNotificationsProvider)
      ? ref.watch(notificationsRepositoryProvider).list()
      : const <PortalNotification>[],
);

final unreadCountProvider = Provider.autoDispose<int>(
  (ref) => ref.watch(notificationsProvider).value?.where((n) => !n.read).length ?? 0,
);

class NotificationsPage extends ConsumerWidget {
  const NotificationsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final notifications = ref.watch(notificationsProvider);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    final repo = ref.read(notificationsRepositoryProvider);

    Future<void> act(Future<void> Function() action, [String? done]) async {
      final messenger = ScaffoldMessenger.of(context);
      try {
        await action();
        if (done != null) messenger.showSnackBar(SnackBar(content: Text(done)));
      } on Object catch (error) {
        messenger.showSnackBar(SnackBar(content: Text(describeError(l, error))));
      }
      ref.invalidate(notificationsProvider);
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(l.nav_notifications),
        actions: [
          IconButton(
            key: const Key('mark-all-read'),
            tooltip: l.notifications_markAllRead,
            icon: const Icon(Icons.done_all),
            onPressed: () => act(() async {
              final count = await repo.markAllRead();
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.notifications_markedAll(count))));
              }
            }),
          ),
        ],
      ),
      body: AsyncView(
        value: notifications,
        onRetry: () => ref.invalidate(notificationsProvider),
        builder: (items) => items.isEmpty
            ? ListView(children: [
                EmptyState(icon: Icons.notifications_none, title: l.notifications_empty, message: l.notifications_emptyCopy),
              ])
            : RefreshIndicator(
                onRefresh: () => ref.refresh(notificationsProvider.future),
                child: ListView.separated(
                  padding: const EdgeInsets.all(16),
                  itemCount: items.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final item = items[index];
                    final color = switch (item.severity) {
                      'critical' => theme.colorScheme.primary,
                      'warning' => const Color(0xFFE0A030),
                      'success' => const Color(0xFF2F9E62),
                      _ => theme.colorScheme.onSurfaceVariant,
                    };
                    return Dismissible(
                      key: Key('notification-${item.id}'),
                      direction: DismissDirection.endToStart,
                      onDismissed: (_) => act(() => repo.update(item.id, archived: true), l.notifications_archived),
                      background: ColoredBox(
                        color: theme.colorScheme.primaryContainer,
                        child: const Align(
                          alignment: AlignmentDirectional.centerEnd,
                          child: Padding(padding: EdgeInsets.all(16), child: Icon(Icons.archive_outlined)),
                        ),
                      ),
                      child: Card(
                        child: ListTile(
                          leading: Icon(item.read ? Icons.notifications_none : Icons.notifications_active, color: color),
                          title: Text(
                            item.title,
                            style: TextStyle(fontWeight: item.read ? FontWeight.w400 : FontWeight.w700),
                          ),
                          subtitle: Text([
                            item.message,
                            if (item.createdAt != null) format.format(item.createdAt!.toLocal()),
                          ].join('\n')),
                          isThreeLine: true,
                          trailing: IconButton(
                            tooltip: item.read ? l.notifications_markUnread : l.notifications_markRead,
                            icon: Icon(item.read ? Icons.mark_email_unread_outlined : Icons.mark_email_read_outlined),
                            onPressed: () => act(() => repo.update(item.id, read: !item.read)),
                          ),
                          onTap: item.read ? null : () => act(() => repo.update(item.id, read: true)),
                        ),
                      ),
                    );
                  },
                ),
              ),
      ),
    );
  }
}
