import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart' show DateFormat, NumberFormat;

import '../../../l10n/generated/app_localizations.dart';
import '../../core/auth/session_controller.dart';
import '../../core/security/device_security.dart';
import '../../widgets/brand_header.dart';
import '../../widgets/error_text.dart';
import '../notifications/notifications.dart';
import '../workspace/workspace_models.dart';
import '../workspace/workspace_repository.dart';

/// Live projects, quota and shortcuts (vip-frontend dashboard-client.tsx).
class DashboardPage extends ConsumerWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final session = ref.watch(sessionProvider).value;
    if (session is! SignedIn) return const SizedBox.shrink();
    final user = session.user;
    final compromised = ref.watch(deviceIntegrityProvider).value?.compromised ?? false;
    final quota = ref.watch(quotaProvider);
    final projects = ref.watch(projectsProvider);

    Future<void> refresh() async {
      ref.invalidate(quotaProvider);
      ref.invalidate(projectsProvider);
      ref.invalidate(notificationsProvider);
      try {
        await ref.read(sessionProvider.notifier).reloadUser();
      } on Object catch (error) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(describeError(l, error))));
        }
      }
    }

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            const BrandMark(size: 32),
            const SizedBox(width: 10),
            Flexible(child: Text(l.dashboard_title, overflow: TextOverflow.ellipsis)),
          ],
        ),
        actions: [
          IconButton(
            key: const Key('open-notifications'),
            tooltip: l.nav_notifications,
            onPressed: () => context.go('/notifications'),
            icon: Badge(
              isLabelVisible: ref.watch(unreadCountProvider) > 0,
              label: Text('${ref.watch(unreadCountProvider)}'),
              child: const Icon(Icons.notifications_outlined),
            ),
          ),
          IconButton(tooltip: l.dashboard_refresh, onPressed: refresh, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: ListView(
          padding: const EdgeInsets.all(20),
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            if (compromised) ...[
              Card(
                key: const Key('device-compromised'),
                color: theme.colorScheme.primaryContainer,
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Text(l.app_deviceCompromised, style: TextStyle(color: theme.colorScheme.onPrimaryContainer)),
                ),
              ),
              const SizedBox(height: 16),
            ],
            Text(l.dashboard_eyebrow, style: theme.textTheme.labelLarge?.copyWith(color: theme.colorScheme.secondary)),
            const SizedBox(height: 6),
            Text(l.dashboard_welcome(user.name), style: theme.textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text(
              l.dashboard_planLine(quota.value?.planName ?? user.organizationPlan, user.role),
              style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 20),
            _QuotaGrid(quota: quota.value, projectCount: projects.value?.where((p) => p.isActive).length),
            if (quota.value?.periodEndsAt != null) ...[
              const SizedBox(height: 8),
              Text(
                l.dashboard_resetsOn(
                  DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).format(quota.value!.periodEndsAt!),
                ),
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
            if (quota.hasError || projects.hasError) ...[
              const SizedBox(height: 12),
              Text(l.dashboard_loadError, style: TextStyle(color: theme.colorScheme.error)),
            ],
            const SizedBox(height: 24),
            Text(l.dashboard_quickActions, style: theme.textTheme.titleMedium),
            const SizedBox(height: 10),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                _Action(icon: Icons.folder_outlined, label: l.dashboard_manageProjects, path: '/projects'),
                _Action(icon: Icons.forum_outlined, label: l.nav_conversations, path: '/conversations'),
                _Action(icon: Icons.auto_awesome, label: l.nav_studio, path: '/studio'),
                _Action(icon: Icons.school_outlined, label: l.app_academy, path: '/academy'),
                _Action(icon: Icons.support_agent, label: l.dashboard_contactSupport, path: '/support'),
                _Action(icon: Icons.manage_accounts_outlined, label: l.dashboard_accountSettings, path: '/profile'),
              ],
            ),
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(child: Text(l.dashboard_recentProjects, style: theme.textTheme.titleMedium)),
                TextButton(onPressed: () => context.go('/projects'), child: Text(l.dashboard_viewProjects)),
              ],
            ),
            const SizedBox(height: 6),
            ...switch (projects) {
              AsyncData(:final value) when value.where((p) => p.isActive).isEmpty => [
                  Text(l.dashboard_noProjects, style: theme.textTheme.titleSmall),
                  Text(l.dashboard_noProjectsCopy, style: theme.textTheme.bodySmall),
                ],
              AsyncData(:final value) => [
                  for (final project in value.where((p) => p.isActive).take(4))
                    Card(
                      margin: const EdgeInsets.only(bottom: 8),
                      child: ListTile(
                        title: Text(project.name),
                        subtitle: Text(l.projects_progress(project.progress)),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => context.go('/projects'),
                      ),
                    ),
                ],
              AsyncError() => const <Widget>[],
              _ => [const Center(child: Padding(padding: EdgeInsets.all(16), child: CircularProgressIndicator()))],
            },
          ],
        ),
      ),
    );
  }
}

class _QuotaGrid extends StatelessWidget {
  const _QuotaGrid({required this.quota, required this.projectCount});

  final PlanQuota? quota;
  final int? projectCount;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final number = NumberFormat.decimalPattern(Localizations.localeOf(context).toLanguageTag());
    String remaining(String key) {
      final q = quota;
      if (q == null) return '…';
      if (q.isUnlimited(key)) return l.dashboard_unlimited;
      final left = q.remaining[key];
      final limit = q.limits[key];
      if (left == null) return '—';
      return limit == null ? number.format(left) : '${number.format(left)} / ${number.format(limit)}';
    }

    String bytes(int value) => value >= 1 << 30
        ? l.app_gb((value / (1 << 30)).toStringAsFixed(1))
        : l.app_mb((value / (1 << 20)).toStringAsFixed(value < 10 << 20 ? 1 : 0));

    final q = quota;
    final used = q?.usage['projects'] ?? projectCount;
    final projectLimit = q?.limits['projects'];
    final storageUsed = q?.usage['storage_bytes'];
    final storageLimit = q?.limits['storage_bytes'];
    final tiles = <(IconData, String, String)>[
      (
        Icons.folder_copy_outlined,
        l.dashboard_projectsUsed,
        used == null
            ? '…'
            : q != null && q.isUnlimited('projects')
                ? '${number.format(used)} · ${l.dashboard_unlimited}'
                : projectLimit == null
                    ? number.format(used)
                    : '${number.format(used)} / ${number.format(projectLimit)}',
      ),
      (Icons.chat_bubble_outline, l.dashboard_messagesRemaining, remaining('user_messages')),
      (Icons.smart_toy_outlined, l.dashboard_responsesRemaining, remaining('assistant_responses')),
      (
        Icons.cloud_outlined,
        l.dashboard_storageUsed,
        storageUsed == null
            ? '—'
            : q!.isUnlimited('storage_bytes') || storageLimit == null
                ? '${bytes(storageUsed)} · ${l.dashboard_unlimited}'
                : '${bytes(storageUsed)} / ${bytes(storageLimit)}',
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth > 640 ? 4 : 2;
        final width = (constraints.maxWidth - (columns - 1) * 10) / columns;
        return Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            for (final (icon, label, value) in tiles)
              SizedBox(
                width: width,
                child: Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(icon, size: 20, color: Theme.of(context).colorScheme.secondary),
                        const SizedBox(height: 8),
                        Text(value, style: Theme.of(context).textTheme.titleMedium),
                        Text(label, style: Theme.of(context).textTheme.bodySmall),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

class _Action extends StatelessWidget {
  const _Action({required this.icon, required this.label, required this.path});

  final IconData icon;
  final String label;
  final String path;

  @override
  Widget build(BuildContext context) {
    return ActionChip(avatar: Icon(icon, size: 18), label: Text(label), onPressed: () => context.go(path));
  }
}
