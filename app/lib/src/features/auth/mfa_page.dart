import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_exception.dart';
import '../../core/auth/models.dart';
import '../../core/auth/session_controller.dart';
import '../../widgets/brand_header.dart';
import '../../widgets/error_text.dart';

/// Second step of sign-in when the account has two-factor authentication.
class MfaPage extends ConsumerStatefulWidget {
  const MfaPage({super.key, required this.challenge});

  final MfaChallenge challenge;

  @override
  ConsumerState<MfaPage> createState() => _MfaPageState();
}

class _MfaPageState extends ConsumerState<MfaPage> {
  final _code = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _verify() async {
    final code = _code.text.trim();
    final l = AppLocalizations.of(context);
    if (_busy || code.length < 6) {
      setState(() => _error = l.auth_mfaCodeError);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(sessionProvider.notifier).verifyMfa(widget.challenge, code);
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = error.failure == ApiFailure.network ? l.app_networkError : l.auth_mfaCodeError);
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeError(l, error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Scaffold(
      body: FormColumn(
        children: [
          const Center(child: BrandMark()),
          const SizedBox(height: 24),
          Text(l.auth_mfaCode, textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 24),
          TextField(
            key: const Key('mfa-code'),
            controller: _code,
            enabled: !_busy,
            autofocus: true,
            textAlign: TextAlign.center,
            textDirection: TextDirection.ltr,
            keyboardType: TextInputType.visiblePassword,
            autofillHints: const [AutofillHints.oneTimeCode],
            autocorrect: false,
            enableSuggestions: false,
            inputFormatters: [
              FilteringTextInputFormatter.allow(RegExp(r'[A-Za-z0-9-]')),
              LengthLimitingTextInputFormatter(32),
            ],
            onSubmitted: (_) => _verify(),
            decoration: InputDecoration(labelText: l.auth_mfaCode),
          ),
          if (_error != null) ...[
            const SizedBox(height: 14),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _busy ? null : _verify,
            child: Text(_busy ? l.auth_verifyingMfa : l.auth_verifyMfa),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: _busy ? null : () => context.go('/login'),
            child: Text(l.auth_useDifferentAccount),
          ),
        ],
      ),
    );
  }
}
