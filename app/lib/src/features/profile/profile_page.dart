import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/auth/session_controller.dart';
import '../../core/locale/locale_controller.dart';
import '../../widgets/error_text.dart';
import '../../widgets/notice.dart';
import '../account/account_repository.dart';
import '../auth/password_recovery_pages.dart';

const _maxAvatarBytes = 2 * 1024 * 1024;

/// Decode a data: URL avatar; anything else (or a broken value) shows initials.
Uint8List? avatarBytes(String? avatar) {
  if (avatar == null || !avatar.startsWith('data:image/')) return null;
  final comma = avatar.indexOf(',');
  if (comma < 0) return null;
  try {
    return base64Decode(avatar.substring(comma + 1));
  } on FormatException {
    return null;
  }
}

String? avatarMime(Uint8List bytes) {
  if (bytes.length > 3 && bytes[0] == 0x89 && bytes[1] == 0x50) return 'image/png';
  if (bytes.length > 2 && bytes[0] == 0xFF && bytes[1] == 0xD8) return 'image/jpeg';
  if (bytes.length > 11 && bytes[8] == 0x57 && bytes[9] == 0x45 && bytes[10] == 0x42 && bytes[11] == 0x50) {
    return 'image/webp';
  }
  if (bytes.length > 3 && bytes[0] == 0x47 && bytes[1] == 0x49 && bytes[2] == 0x46) return 'image/gif';
  return null;
}

class ProfilePage extends ConsumerStatefulWidget {
  const ProfilePage({super.key});

  @override
  ConsumerState<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends ConsumerState<ProfilePage> {
  final _name = TextEditingController();
  bool _busy = false;
  String? _message;
  NoticeTone _tone = NoticeTone.info;
  String? _loadedName;

  @override
  void initState() {
    super.initState();
    _name.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _save({String? name, String? avatar}) async {
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      final updated = await ref.read(accountRepositoryProvider).update(name: name, avatar: avatar);
      ref.invalidate(accountSettingsProvider);
      await ref.read(sessionProvider.notifier).reloadUser();
      if (mounted) {
        setState(() {
          _loadedName = updated.name;
          _message = l.profile_profileSaved;
          _tone = NoticeTone.success;
        });
      }
    } on Object catch (error) {
      if (mounted) {
        setState(() {
          _message = describeAccountError(l, error, l.profile_saveError);
          _tone = NoticeTone.error;
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _showError(String message) => setState(() {
        _message = message;
        _tone = NoticeTone.error;
      });

  Future<void> _pickAvatar() async {
    final l = AppLocalizations.of(context);
    final Uint8List bytes;
    try {
      final file = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 512, maxHeight: 512, imageQuality: 85);
      if (file == null) return;
      bytes = await file.readAsBytes();
    } on Object catch (error) {
      debugPrint('profile photo could not be read: $error');
      if (mounted) _showError(l.profile_avatarReadError);
      return;
    }
    final mime = avatarMime(bytes);
    if (!mounted) return;
    if (mime == null) {
      _showError(l.profile_avatarTypeError);
      return;
    }
    if (bytes.length > _maxAvatarBytes) {
      _showError(l.profile_avatarSizeError);
      return;
    }
    await _save(avatar: 'data:$mime;base64,${base64Encode(bytes)}');
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final settings = ref.watch(accountSettingsProvider);
    final selected = ref.watch(localeProvider);
    return Scaffold(
      appBar: AppBar(title: Text(l.profile_eyebrow)),
      body: settings.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(describeAccountError(l, error, l.profile_loadError), textAlign: TextAlign.center),
                const SizedBox(height: 16),
                FilledButton(onPressed: () => ref.invalidate(accountSettingsProvider), child: Text(l.app_retry)),
              ],
            ),
          ),
        ),
        data: (account) {
          if (_loadedName != account.name) {
            _loadedName = account.name;
            _name.text = account.name;
          }
          final photo = avatarBytes(account.avatar);
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Center(
                child: CircleAvatar(
                  radius: 44,
                  backgroundColor: theme.colorScheme.primaryContainer,
                  backgroundImage: photo == null ? null : MemoryImage(photo),
                  child: photo == null
                      ? Text(
                          account.name.isEmpty ? '?' : account.name.characters.first.toUpperCase(),
                          style: theme.textTheme.headlineMedium,
                        )
                      : null,
                ),
              ),
              const SizedBox(height: 8),
              Center(
                child: TextButton.icon(
                  key: const Key('change-photo'),
                  onPressed: _busy ? null : _pickAvatar,
                  icon: const Icon(Icons.photo_camera_outlined),
                  label: Text(l.app_changePhoto),
                ),
              ),
              Text(
                l.profile_avatarRule,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 20),
              TextField(
                key: const Key('profile-name'),
                controller: _name,
                enabled: account.canEditName && !_busy,
                decoration: InputDecoration(labelText: l.profile_name),
              ),
              if (!account.canEditName) ...[
                const SizedBox(height: 6),
                Text(
                  l.profile_freeNameLocked,
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ] else ...[
                const SizedBox(height: 12),
                FilledButton(
                  key: const Key('profile-save'),
                  onPressed: _busy || _name.text.trim().length < 2 ? null : () => _save(name: _name.text.trim()),
                  child: Text(_busy ? l.profile_saving : l.profile_saveProfile),
                ),
              ],
              if (_message != null) ...[
                const SizedBox(height: 14),
                Notice(key: const Key('profile-message'), text: _message!, tone: _tone),
              ],
              const SizedBox(height: 20),
              Card(
                child: Column(
                  children: [
                    ListTile(
                      title: Text(l.profile_email),
                      subtitle: Text(account.email, textDirection: TextDirection.ltr),
                    ),
                    ListTile(title: Text(l.profile_role), subtitle: Text(account.role)),
                    ListTile(title: Text(l.profile_organization), subtitle: Text(account.organization)),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              Card(
                child: ListTile(
                  key: const Key('open-security'),
                  leading: const Icon(Icons.shield_outlined),
                  title: Text(l.profile_accountSecurityTitle),
                  subtitle: Text(
                    account.mfaEnabled
                        ? l.profile_mfaActive(account.backupCodesRemaining)
                        : l.profile_mfaInactive,
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.go('/profile/security'),
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
                onPressed: () async {
                  try {
                    await ref.read(sessionProvider.notifier).signOut();
                  } on Object catch (error) {
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(describeError(l, error))));
                    }
                  }
                },
              ),
            ],
          );
        },
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
