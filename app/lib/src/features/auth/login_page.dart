import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/auth/models.dart';
import '../../core/auth/session_controller.dart';
import '../../widgets/brand_header.dart';
import '../../widgets/error_text.dart';
import 'register_page.dart';

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _formKey = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy || !(_formKey.currentState?.validate() ?? false)) return;
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final outcome = await ref.read(sessionProvider.notifier).signIn(_email.text, _password.text);
      if (!mounted) return;
      if (outcome is LoginNeedsMfa) context.go('/login/mfa', extra: outcome.challenge);
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeLoginError(l, error));
    } finally {
      if (mounted) {
        _password.clear();
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final session = ref.watch(sessionProvider).value;
    final notice = switch (session) {
      SignedOut(notice: SignOutNotice.expired) => l.app_sessionExpired,
      SignedOut(notice: SignOutNotice.passwordChanged) => l.passwordRecovery_resetSuccess,
      SignedOut(notice: SignOutNotice.mfaDisabled) => l.profile_mfaDisabled,
      SignedOut(notice: SignOutNotice.accountDeleted) => l.app_accountDeleted,
      _ => null,
    };
    return Scaffold(
      body: AutofillGroup(
        child: Form(
          key: _formKey,
          child: FormColumn(
            children: [
              const Center(child: BrandMark()),
              const SizedBox(height: 24),
              Text(l.auth_loginTitle, textAlign: TextAlign.center, style: theme.textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text(
                l.auth_secureAccess,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 28),
              if (notice != null && _error == null) ...[
                _Banner(key: const Key('login-notice'), text: notice),
                const SizedBox(height: 16),
              ],
              TextFormField(
                key: const Key('login-email'),
                controller: _email,
                enabled: !_busy,
                keyboardType: TextInputType.emailAddress,
                textInputAction: TextInputAction.next,
                autofillHints: const [AutofillHints.username, AutofillHints.email],
                autocorrect: false,
                enableSuggestions: false,
                textDirection: TextDirection.ltr,
                inputFormatters: [LengthLimitingTextInputFormatter(254)],
                decoration: InputDecoration(labelText: l.auth_email),
                validator: (value) {
                  final text = value?.trim() ?? '';
                  return RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(text) ? null : l.auth_email;
                },
              ),
              const SizedBox(height: 14),
              TextFormField(
                key: const Key('login-password'),
                controller: _password,
                enabled: !_busy,
                obscureText: _obscure,
                autocorrect: false,
                enableSuggestions: false,
                textDirection: TextDirection.ltr,
                autofillHints: const [AutofillHints.password],
                textInputAction: TextInputAction.done,
                inputFormatters: [LengthLimitingTextInputFormatter(256)],
                onFieldSubmitted: (_) => _submit(),
                decoration: InputDecoration(
                  labelText: l.auth_password,
                  suffixIcon: IconButton(
                    tooltip: l.auth_password,
                    icon: Icon(_obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                    onPressed: () => setState(() => _obscure = !_obscure),
                  ),
                ),
                validator: (value) => (value == null || value.isEmpty) ? l.auth_password : null,
              ),
              Align(
                alignment: AlignmentDirectional.centerEnd,
                child: TextButton(
                  key: const Key('forgot-password'),
                  onPressed: _busy ? null : () => context.go('/login/forgot'),
                  child: Text(l.auth_forgotPassword),
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                _Banner(key: const Key('login-error'), text: _error!),
              ],
              const SizedBox(height: 24),
              FilledButton(
                key: const Key('login-submit'),
                onPressed: _busy ? null : _submit,
                child: Text(_busy ? l.auth_signingIn : l.auth_signIn),
              ),
              const SizedBox(height: 8),
              TextButton(
                key: const Key('create-account'),
                onPressed: _busy
                    ? null
                    : () => kIsWeb ? openWebsiteRegistration(context) : context.go('/login/register'),
                child: Text('${l.auth_noAccount} ${l.auth_createAccount}'),
              ),
              const SizedBox(height: 12),
              Text(
                l.auth_securityNote,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      liveRegion: true,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: scheme.primaryContainer,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: scheme.primary.withValues(alpha: 0.5)),
        ),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Text(text, style: TextStyle(color: scheme.onPrimaryContainer)),
        ),
      ),
    );
  }
}
