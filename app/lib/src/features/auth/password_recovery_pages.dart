import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_exception.dart';
import '../../widgets/brand_header.dart';
import '../../widgets/error_text.dart';
import '../../widgets/notice.dart';
import '../account/account_repository.dart';

final _emailPattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

/// Step 1: ask for recovery instructions by email.
class ForgotPasswordPage extends ConsumerStatefulWidget {
  const ForgotPasswordPage({super.key});

  @override
  ConsumerState<ForgotPasswordPage> createState() => _ForgotPasswordPageState();
}

class _ForgotPasswordPageState extends ConsumerState<ForgotPasswordPage> {
  final _formKey = GlobalKey<FormState>();
  final _email = TextEditingController();
  bool _busy = false;
  bool _sent = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (_busy || !(_formKey.currentState?.validate() ?? false)) return;
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(accountRepositoryProvider).requestPasswordReset(_email.text);
      if (mounted) setState(() => _sent = true);
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = error.failure == ApiFailure.rateLimited
            ? l.auth_tooManyAttempts
            : error.failure == ApiFailure.network
                ? l.app_networkError
                : l.passwordRecovery_requestError);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(leading: BackButton(onPressed: () => context.go('/login'))),
      body: Form(
        key: _formKey,
        child: FormColumn(
          children: [
            const Center(child: BrandMark()),
            const SizedBox(height: 20),
            Text(l.passwordRecovery_forgotTitle, textAlign: TextAlign.center, style: theme.textTheme.headlineSmall),
            const SizedBox(height: 8),
            Text(
              l.passwordRecovery_forgotDescription,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 24),
            if (_sent)
              Notice(key: const Key('forgot-sent'), text: l.passwordRecovery_requestSuccess, tone: NoticeTone.success)
            else ...[
              TextFormField(
                key: const Key('forgot-email'),
                controller: _email,
                enabled: !_busy,
                keyboardType: TextInputType.emailAddress,
                autofillHints: const [AutofillHints.email],
                autocorrect: false,
                textDirection: TextDirection.ltr,
                decoration: InputDecoration(labelText: l.passwordRecovery_email),
                validator: (value) => _emailPattern.hasMatch(value?.trim() ?? '') ? null : l.passwordRecovery_email,
                onFieldSubmitted: (_) => _send(),
              ),
              if (_error != null) ...[
                const SizedBox(height: 14),
                Notice(text: _error!, tone: NoticeTone.error),
              ],
              const SizedBox(height: 20),
              FilledButton(
                key: const Key('forgot-send'),
                onPressed: _busy ? null : _send,
                child: Text(_busy ? l.passwordRecovery_sending : l.passwordRecovery_send),
              ),
            ],
            const SizedBox(height: 12),
            TextButton(onPressed: () => context.go('/login'), child: Text(l.passwordRecovery_backToLogin)),
          ],
        ),
      ),
    );
  }
}

/// Step 2: the link in the email (…/reset-password?token=…) sets a new password.
class ResetPasswordPage extends ConsumerStatefulWidget {
  const ResetPasswordPage({super.key, required this.token});

  final String token;

  @override
  ConsumerState<ResetPasswordPage> createState() => _ResetPasswordPageState();
}

class _ResetPasswordPageState extends ConsumerState<ResetPasswordPage> {
  static const _minLength = 12;
  final _formKey = GlobalKey<FormState>();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;
  bool _done = false;
  String? _error;

  @override
  void dispose() {
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _reset() async {
    if (_busy || !(_formKey.currentState?.validate() ?? false)) return;
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(accountRepositoryProvider).confirmPasswordReset(widget.token, _password.text);
      if (mounted) setState(() => _done = true);
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = switch (error.statusCode) {
              400 => l.passwordRecovery_invalidToken,
              409 => l.passwordRecovery_samePassword,
              422 => error.message,
              _ => error.failure == ApiFailure.network ? l.app_networkError : l.passwordRecovery_resetError,
            });
      }
    } finally {
      if (mounted) {
        _password.clear();
        _confirm.clear();
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final validToken = widget.token.length >= 16;
    return Scaffold(
      body: Form(
        key: _formKey,
        child: FormColumn(
          children: [
            const Center(child: BrandMark()),
            const SizedBox(height: 20),
            Text(l.passwordRecovery_resetTitle, textAlign: TextAlign.center, style: theme.textTheme.headlineSmall),
            const SizedBox(height: 8),
            Text(
              l.passwordRecovery_resetDescription,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 24),
            if (_done)
              Notice(key: const Key('reset-done'), text: l.passwordRecovery_resetSuccess, tone: NoticeTone.success)
            else if (!validToken)
              Notice(text: l.passwordRecovery_invalidToken, tone: NoticeTone.error)
            else ...[
              PasswordField(
                key: const Key('reset-password'),
                controller: _password,
                label: l.passwordRecovery_newPassword,
                enabled: !_busy,
                newPassword: true,
                validator: (value) =>
                    (value?.length ?? 0) >= _minLength ? null : l.profile_passwordMinimum(_minLength),
              ),
              const SizedBox(height: 14),
              PasswordField(
                key: const Key('reset-confirm'),
                controller: _confirm,
                label: l.passwordRecovery_confirmPassword,
                enabled: !_busy,
                newPassword: true,
                validator: (value) => value == _password.text ? null : l.passwordRecovery_mismatch,
                onSubmitted: (_) => _reset(),
              ),
              if (_error != null) ...[
                const SizedBox(height: 14),
                Notice(key: const Key('reset-error'), text: _error!, tone: NoticeTone.error),
              ],
              const SizedBox(height: 20),
              FilledButton(
                key: const Key('reset-submit'),
                onPressed: _busy ? null : _reset,
                child: Text(_busy ? l.passwordRecovery_resetting : l.passwordRecovery_reset),
              ),
            ],
            const SizedBox(height: 12),
            TextButton(onPressed: () => context.go('/login'), child: Text(l.passwordRecovery_backToLogin)),
          ],
        ),
      ),
    );
  }
}

/// Shared by the security screen.
String describeAccountError(AppLocalizations l, Object error, String fallback) {
  if (error is ApiException && error.failure == ApiFailure.network) return l.app_networkError;
  if (error is ApiException && error.failure == ApiFailure.validation) return error.message;
  return error is ApiException ? fallback : describeError(l, error);
}
