import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/auth/session_controller.dart';
import '../../core/security/device_security.dart';
import '../../widgets/brand_header.dart';
import '../../widgets/error_text.dart';

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
    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            const BrandMark(size: 32),
            const SizedBox(width: 10),
            Text(l.dashboard_title),
          ],
        ),
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            await ref.read(sessionProvider.notifier).reloadUser();
          } on Object catch (error) {
            if (context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(describeError(l, error))));
            }
          }
        },
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
            const SizedBox(height: 20),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(l.dashboard_planLine(user.organizationPlan, user.role), style: theme.textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Text(
                      l.dashboard_organization(user.organizationName),
                      style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
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
