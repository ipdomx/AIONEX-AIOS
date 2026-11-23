import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart' show DateFormat;
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/auth/session_controller.dart';
import '../../widgets/notice.dart';
import '../account/account_repository.dart';
import '../auth/password_recovery_pages.dart';

/// Password, two-factor authentication and sessions (same rules as the website's
/// AccountSecurityManager). Shown inside SecureScreen: setup keys and recovery
/// codes never land in screenshots.
class AccountSecurityPage extends ConsumerWidget {
  const AccountSecurityPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final settings = ref.watch(accountSettingsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(l.profile_accountSecurityTitle)),
      body: settings.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(describeAccountError(l, error, l.profile_securityLoadError), textAlign: TextAlign.center),
                const SizedBox(height: 16),
                FilledButton(onPressed: () => ref.invalidate(accountSettingsProvider), child: Text(l.app_retry)),
              ],
            ),
          ),
        ),
        data: (account) => ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Text(
              l.profile_accountSecurityDescription,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
            const SizedBox(height: 20),
            _MfaSection(account: account),
            const SizedBox(height: 20),
            _PasswordSection(account: account),
            const SizedBox(height: 20),
            const _SessionsSection(),
          ],
        ),
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.children, this.subtitle});

  final String title;
  final String? subtitle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(title, style: theme.textTheme.titleMedium),
            if (subtitle != null) ...[
              const SizedBox(height: 6),
              Text(subtitle!, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
            ],
            const SizedBox(height: 14),
            ...children,
          ],
        ),
      ),
    );
  }
}

class _PasswordSection extends ConsumerStatefulWidget {
  const _PasswordSection({required this.account});

  final AccountSettings account;

  @override
  ConsumerState<_PasswordSection> createState() => _PasswordSectionState();
}

class _PasswordSectionState extends ConsumerState<_PasswordSection> {
  final _formKey = GlobalKey<FormState>();
  final _current = TextEditingController();
  final _next = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _change() async {
    if (_busy || !(_formKey.currentState?.validate() ?? false)) return;
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(accountRepositoryProvider).changePassword(_current.text, _next.text);
      // Every session was revoked by the server, including this one.
      await ref.read(sessionProvider.notifier).signOut(notice: SignOutNotice.passwordChanged);
    } on Object catch (error) {
      if (mounted) {
        setState(() => _error = describeAccountError(l, error, l.profile_passwordError));
      }
    } finally {
      if (mounted) {
        _current.clear();
        _next.clear();
        _confirm.clear();
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final min = widget.account.passwordMinLength;
    return Form(
      key: _formKey,
      child: _Section(
        title: l.profile_passwordTitle,
        subtitle: l.profile_passwordDescription,
        children: [
          PasswordField(
            key: const Key('password-current'),
            controller: _current,
            label: l.profile_currentPassword,
            enabled: !_busy,
            validator: (value) => (value?.isEmpty ?? true) ? l.profile_currentPassword : null,
          ),
          const SizedBox(height: 12),
          PasswordField(
            key: const Key('password-new'),
            controller: _next,
            label: l.profile_newPassword,
            enabled: !_busy,
            newPassword: true,
            validator: (value) => (value?.length ?? 0) >= min ? null : l.profile_passwordMinimum(min),
          ),
          const SizedBox(height: 12),
          PasswordField(
            key: const Key('password-confirm'),
            controller: _confirm,
            label: l.profile_confirmPassword,
            enabled: !_busy,
            newPassword: true,
            validator: (value) => value == _next.text ? null : l.profile_passwordMismatch,
          ),
          const SizedBox(height: 10),
          Text(l.profile_sessionNotice(widget.account.activeSessions), style: Theme.of(context).textTheme.bodySmall),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Notice(key: const Key('password-error'), text: _error!, tone: NoticeTone.error),
          ],
          const SizedBox(height: 14),
          FilledButton(
            key: const Key('password-submit'),
            onPressed: _busy ? null : _change,
            child: Text(_busy ? l.profile_updatingPassword : l.profile_updatePassword),
          ),
        ],
      ),
    );
  }
}

class _MfaSection extends ConsumerStatefulWidget {
  const _MfaSection({required this.account});

  final AccountSettings account;

  @override
  ConsumerState<_MfaSection> createState() => _MfaSectionState();
}

class _MfaSectionState extends ConsumerState<_MfaSection> {
  final _code = TextEditingController();
  final _password = TextEditingController();
  MfaSetup? _setup;
  bool _busy = false;
  String? _message;
  NoticeTone _tone = NoticeTone.info;

  @override
  void dispose() {
    _code.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action, String fallback) async {
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      await action();
    } on Object catch (error) {
      if (mounted) {
        setState(() {
          _message = describeAccountError(l, error, fallback);
          _tone = NoticeTone.error;
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _start() => _run(() async {
        final setup = await ref.read(accountRepositoryProvider).startMfaSetup();
        if (mounted) setState(() => _setup = setup);
      }, AppLocalizations.of(context).profile_mfaSetupError);

  Future<void> _verify() {
    final l = AppLocalizations.of(context);
    return _run(() async {
      await ref.read(accountRepositoryProvider).verifyMfaSetup(_code.text);
      _code.clear();
      if (!mounted) return;
      setState(() {
        _setup = null;
        _message = l.profile_mfaEnabled;
        _tone = NoticeTone.success;
      });
      ref.invalidate(accountSettingsProvider);
    }, l.profile_mfaCodeError);
  }

  Future<void> _disable() {
    final l = AppLocalizations.of(context);
    return _run(() async {
      await ref.read(accountRepositoryProvider).disableMfa(_password.text, _code.text);
      _password.clear();
      _code.clear();
      // The server revoked every session.
      await ref.read(sessionProvider.notifier).signOut(notice: SignOutNotice.mfaDisabled);
    }, l.profile_mfaDisableError);
  }

  Future<void> _copy(String text) async {
    final l = AppLocalizations.of(context);
    await Clipboard.setData(ClipboardData(text: text));
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.app_copied)));
  }

  Widget _codeField(AppLocalizations l) => TextField(
        key: const Key('mfa-setup-code'),
        controller: _code,
        enabled: !_busy,
        textDirection: TextDirection.ltr,
        keyboardType: TextInputType.number,
        autofillHints: const [AutofillHints.oneTimeCode],
        inputFormatters: [
          FilteringTextInputFormatter.allow(RegExp(r'[A-Za-z0-9-]')),
          LengthLimitingTextInputFormatter(32),
        ],
        decoration: InputDecoration(labelText: l.profile_mfaCode),
      );

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final account = widget.account;
    final setup = _setup;
    final children = <Widget>[];
    if (account.mfaEnabled) {
      children.addAll([
        Text(l.profile_mfaActive(account.backupCodesRemaining)),
        const SizedBox(height: 14),
        PasswordField(controller: _password, label: l.profile_currentPassword, enabled: !_busy),
        const SizedBox(height: 12),
        _codeField(l),
        const SizedBox(height: 14),
        OutlinedButton(
          key: const Key('mfa-disable'),
          onPressed: _busy ? null : _disable,
          child: Text(l.profile_disableMfa),
        ),
      ]);
    } else if (setup == null) {
      children.addAll([
        Text(l.profile_mfaInactive),
        const SizedBox(height: 14),
        FilledButton(key: const Key('mfa-enable'), onPressed: _busy ? null : _start, child: Text(l.profile_enableMfa)),
      ]);
    } else {
      children.addAll([
        Text(l.app_scanOrOpen),
        const SizedBox(height: 14),
        Center(
          child: ColoredBox(
            color: Colors.white,
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: QrImageView(data: setup.otpauthUri, size: 190, semanticsLabel: l.profile_mfaTitle),
            ),
          ),
        ),
        const SizedBox(height: 10),
        if (!kIsWeb)
          OutlinedButton.icon(
            icon: const Icon(Icons.open_in_new),
            label: Text(l.app_openAuthenticator),
            onPressed: () => launchUrl(Uri.parse(setup.otpauthUri), mode: LaunchMode.externalApplication),
          ),
        const SizedBox(height: 10),
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(l.app_setupKey),
          subtitle: SelectableText(setup.secret, textDirection: TextDirection.ltr),
          trailing: IconButton(
            tooltip: l.app_copy,
            icon: const Icon(Icons.copy),
            onPressed: () => _copy(setup.secret),
          ),
        ),
        const SizedBox(height: 6),
        Text(l.profile_backupCodes, style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 6),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final code in setup.backupCodes)
              Chip(label: Text(code, textDirection: TextDirection.ltr, style: const TextStyle(fontFamily: 'monospace'))),
          ],
        ),
        TextButton.icon(
          onPressed: () => _copy(setup.backupCodes.join('\n')),
          icon: const Icon(Icons.copy_all),
          label: Text(l.app_copy),
        ),
        const SizedBox(height: 10),
        _codeField(l),
        const SizedBox(height: 14),
        FilledButton(
          key: const Key('mfa-verify'),
          onPressed: _busy ? null : _verify,
          child: Text(l.profile_verifyMfa),
        ),
      ]);
    }
    if (_message != null) {
      children.addAll([const SizedBox(height: 12), Notice(key: const Key('mfa-message'), text: _message!, tone: _tone)]);
    }
    return _Section(title: l.profile_mfaTitle, children: children);
  }
}

class _SessionsSection extends ConsumerWidget {
  const _SessionsSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final sessions = ref.watch(accountSessionsProvider);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    return _Section(
      title: l.profile_sessionsTitle,
      children: [
        sessions.when(
          loading: () => const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator())),
          error: (error, _) => Text(describeAccountError(l, error, l.profile_securityLoadError)),
          data: (items) {
            if (items.isEmpty) return Text(l.profile_noSessions);
            return Column(
              children: [
                for (final item in items.take(20))
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(item.active ? Icons.devices : Icons.history),
                    title: Text(
                      item.userAgent?.isNotEmpty == true ? item.userAgent! : l.profile_unknownDevice,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    subtitle: Text(
                      [
                        item.ipAddress ?? l.profile_unknownAddress,
                        if (item.createdAt != null) format.format(item.createdAt!.toLocal()),
                        item.active ? l.profile_activeSession : l.profile_closedSession,
                      ].join(' · '),
                    ),
                    trailing: item.active
                        ? IconButton(
                            tooltip: l.profile_revokeSession,
                            icon: const Icon(Icons.logout),
                            onPressed: () async {
                              final messenger = ScaffoldMessenger.of(context);
                              try {
                                await ref.read(accountRepositoryProvider).revokeSession(item.id);
                                messenger.showSnackBar(SnackBar(content: Text(l.profile_sessionRevoked)));
                              } on Object {
                                messenger.showSnackBar(SnackBar(content: Text(l.profile_sessionRevokeError)));
                              }
                              ref.invalidate(accountSessionsProvider);
                            },
                          )
                        : null,
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}
