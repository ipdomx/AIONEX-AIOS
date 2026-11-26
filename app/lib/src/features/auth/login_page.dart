import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_exception.dart';
import '../../core/auth/auth_repository.dart';
import '../../core/auth/models.dart';
import '../../core/auth/session_controller.dart';
import '../../core/firebase/firebase_setup.dart';
import '../../core/providers.dart';
import '../../widgets/brand_header.dart';
import '../../widgets/error_text.dart';
import 'register_page.dart';

/// Google / Apple / Facebook buttons: only providers the owner switched on and
/// the phone can run (Firebase configured in this build). None on the web build.
final socialSignInProvidersProvider = FutureProvider.autoDispose<List<SocialProvider>>((ref) async {
  if (kIsWeb) return const [];
  if (!await ref.watch(firebaseReadyProvider.future)) return const [];
  try {
    final all = await ref.watch(authRepositoryProvider).socialProviders();
    final usable = [for (final p in all) if (FirebaseSocialSigner.providerFor(p.firebaseProvider) != null) p];
    // Apple's guideline: on iPhone, Sign in with Apple comes first.
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      usable.sort((a, b) => (a.id == 'apple' ? 0 : 1).compareTo(b.id == 'apple' ? 0 : 1));
    }
    return usable;
  } on Object {
    return const [];
  }
});

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

  Future<void> _social(SocialProvider provider) async {
    if (_busy) return;
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final token = await ref.read(socialSignerProvider).idToken(provider.firebaseProvider);
      final outcome = await ref.read(sessionProvider.notifier).signInWithSocial(token);
      if (!mounted) return;
      if (outcome is LoginNeedsMfa) context.go('/login/mfa', extra: outcome.challenge);
    } on SocialSignInCancelled {
      // Closed the provider sheet: nothing to report.
    } on SocialRegistrationRequired catch (needed) {
      if (mounted) context.go('/login/register', extra: needed.registration);
    } on Object catch (error) {
      if (mounted) {
        setState(() => _error = error is ApiException && error.failure == ApiFailure.server
            ? l.auth_socialUnavailable
            : error is ApiException || error is OwnerConsoleOnlyException
                ? describeLoginError(l, error)
                : l.auth_socialError);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final session = ref.watch(sessionProvider).value;
    final socialProviders = ref.watch(socialSignInProvidersProvider).value ?? const <SocialProvider>[];
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
              if (socialProviders.isNotEmpty) ...[
                const SizedBox(height: 20),
                Row(
                  children: [
                    const Expanded(child: Divider()),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: Text(l.auth_socialDivider, style: theme.textTheme.bodySmall),
                    ),
                    const Expanded(child: Divider()),
                  ],
                ),
                const SizedBox(height: 12),
                for (final provider in socialProviders) ...[
                  OutlinedButton.icon(
                    key: Key('social-${provider.id}'),
                    onPressed: _busy ? null : () => _social(provider),
                    icon: Icon(switch (provider.id) {
                      'apple' => Icons.apple,
                      'google' => Icons.g_mobiledata,
                      'facebook' => Icons.facebook,
                      _ => Icons.login,
                    }),
                    label: Text(l.app_continueWith(provider.label)),
                  ),
                  const SizedBox(height: 8),
                ],
              ],
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
