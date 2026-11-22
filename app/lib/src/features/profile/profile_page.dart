import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/auth/session_controller.dart';
import '../../core/locale/locale_controller.dart';

class ProfilePage extends ConsumerWidget {
  const ProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final session = ref.watch(sessionProvider).value;
    final selected = ref.watch(localeProvider);
    if (session is! SignedIn) return const SizedBox.shrink();
    final user = session.user;
    return Scaffold(
      appBar: AppBar(title: Text(l.profile_eyebrow)),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Card(
            child: Column(
              children: [
                ListTile(title: Text(l.profile_name), subtitle: Text(user.name)),
                ListTile(
                  title: Text(l.profile_email),
                  subtitle: Text(user.email, textDirection: TextDirection.ltr),
                ),
                ListTile(title: Text(l.profile_role), subtitle: Text(user.role)),
                ListTile(title: Text(l.profile_organization), subtitle: Text(user.organizationName)),
              ],
            ),
          ),
          const SizedBox(height: 24),
          Text(l.nav_language, style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          Card(
            child: RadioGroup<String>(
              groupValue: selected?.languageCode ?? '',
              onChanged: (code) {
                final locale = supportedLocales.where((item) => item.languageCode == code).firstOrNull;
                ref.read(localeProvider.notifier).select(locale);
              },
              child: Column(
                children: [
                  RadioListTile<String>(value: '', title: Text(l.app_systemLanguage)),
                  for (final locale in supportedLocales)
                    RadioListTile<String>(
                      value: locale.languageCode,
                      title: Text(_languageName(l, locale.languageCode)),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            key: const Key('sign-out'),
            icon: const Icon(Icons.logout),
            label: Text(l.nav_logout),
            onPressed: () => ref.read(sessionProvider.notifier).signOut(),
          ),
        ],
      ),
    );
  }

  static String _languageName(AppLocalizations l, String code) {
    return switch (code) {
      'ar' => l.app_languageName_ar,
      'de' => l.app_languageName_de,
      'es' => l.app_languageName_es,
      'fr' => l.app_languageName_fr,
      'tr' => l.app_languageName_tr,
      _ => l.app_languageName_en,
    };
  }
}
