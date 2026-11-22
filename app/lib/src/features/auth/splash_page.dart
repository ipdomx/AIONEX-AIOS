import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/auth/session_controller.dart';
import '../../widgets/brand_header.dart';
import '../../widgets/error_text.dart';

/// Shown while the saved session is restored, or when restoring it failed.
class SplashPage extends ConsumerWidget {
  const SplashPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final session = ref.watch(sessionProvider);
    return Scaffold(
      body: FormColumn(
        children: [
          const Center(child: BrandMark(size: 96)),
          const SizedBox(height: 32),
          if (session.hasError) ...[
            Text(
              describeError(l, session.error!),
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyLarge,
            ),
            const SizedBox(height: 20),
            FilledButton(
              onPressed: () => ref.read(sessionProvider.notifier).retry(),
              child: Text(l.app_retry),
            ),
          ] else
            Center(
              child: Semantics(label: l.app_loading, child: const CircularProgressIndicator()),
            ),
        ],
      ),
    );
  }
}
