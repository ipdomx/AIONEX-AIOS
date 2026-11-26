import 'dart:io' show Platform;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart' show DateFormat;
import 'package:url_launcher/url_launcher.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_exception.dart';
import '../../core/auth/models.dart';
import '../../core/auth/session_controller.dart';
import '../../core/firebase/firebase_setup.dart';
import '../../core/providers.dart';
import '../../widgets/brand_header.dart';
import '../../widgets/notice.dart';

final _usernamePattern = RegExp(r'^[A-Za-z0-9_.-]{3,32}$');
final _phonePattern = RegExp(r'^\+[1-9][0-9]{7,14}$');
final _emailPattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

/// Same normalisation as the website: lower case, allowed characters only.
String normalizeUsername(String value) =>
    value.trim().toLowerCase().replaceAll(RegExp(r'\s+'), '').replaceAll(RegExp(r'[^a-z0-9_.-]'), '');

final registrationPolicyProvider = FutureProvider.autoDispose<RegistrationPolicy>(
  (ref) => ref.watch(authRepositoryProvider).registrationPolicy(),
);

String _providerLabel(String id) => switch (id) {
      'google' => 'Google',
      'apple' => 'Apple',
      'facebook' => 'Facebook',
      _ => id,
    };

enum _PhoneStage { idle, sending, code, confirming, verified }

/// Free sign-up with SMS verification (the website's register page, natively).
class RegisterPage extends ConsumerStatefulWidget {
  const RegisterPage({super.key, this.social});

  /// Set when Google / Apple verified an email that has no account yet.
  final SocialRegistration? social;

  @override
  ConsumerState<RegisterPage> createState() => _RegisterPageState();
}

class _RegisterPageState extends ConsumerState<RegisterPage> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _username = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  final _country = TextEditingController(text: ui.PlatformDispatcher.instance.locale.countryCode ?? '');
  final _phone = TextEditingController();
  final _code = TextEditingController();
  DateTime? _birthDate;
  bool _consent = false;
  _PhoneStage _stage = _PhoneStage.idle;
  String? _idToken;
  String? _phoneError;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    final social = widget.social;
    if (social != null) {
      _email.text = social.email;
      if (social.name != null) _name.text = social.name!;
    }
  }

  @override
  void dispose() {
    for (final c in [_name, _username, _email, _password, _confirm, _country, _phone, _code]) {
      c.dispose();
    }
    super.dispose();
  }

  void _phoneChanged(String _) {
    if (_stage != _PhoneStage.idle) {
      setState(() {
        _stage = _PhoneStage.idle;
        _idToken = null;
        _code.clear();
      });
    }
  }

  Future<void> _sendCode() async {
    final l = AppLocalizations.of(context);
    final phone = _phone.text.trim();
    if (!_phonePattern.hasMatch(phone)) {
      setState(() => _phoneError = l.register_phoneFormatError);
      return;
    }
    setState(() {
      _phoneError = null;
      _stage = _PhoneStage.sending;
    });
    try {
      final token = await ref.read(phoneVerifierProvider).sendCode(phone);
      if (!mounted) return;
      setState(() {
        _idToken = token;
        _stage = token == null ? _PhoneStage.code : _PhoneStage.verified;
      });
    } on StateError {
      if (mounted) {
        setState(() {
          _stage = _PhoneStage.idle;
          _phoneError = l.register_phoneUnavailable;
        });
      }
    } on Object {
      if (mounted) {
        setState(() {
          _stage = _PhoneStage.idle;
          _phoneError = l.register_phoneSendError;
        });
      }
    }
  }

  Future<void> _confirmCode() async {
    final l = AppLocalizations.of(context);
    if (_code.text.trim().length < 6) return;
    setState(() {
      _phoneError = null;
      _stage = _PhoneStage.confirming;
    });
    try {
      final token = await ref.read(phoneVerifierProvider).confirmCode(_code.text);
      if (mounted) {
        setState(() {
          _idToken = token;
          _stage = _PhoneStage.verified;
        });
      }
    } on Object {
      if (mounted) {
        setState(() {
          _stage = _PhoneStage.code;
          _phoneError = l.register_phoneConfirmError;
        });
      }
    }
  }

  Map<String, Object?> _telemetry(BuildContext context) {
    final view = View.of(context);
    final size = view.physicalSize / view.devicePixelRatio;
    return {
      'timezone': DateTime.now().timeZoneName,
      'language': Localizations.localeOf(context).toLanguageTag(),
      'platform': defaultTargetPlatform.name,
      'screen': '${size.width.round()}x${size.height.round()}',
      'screen_width': size.width.round(),
      'screen_height': size.height.round(),
      'user_agent': 'aionex-app/${ref.read(appConfigProvider).appVersion} (${defaultTargetPlatform.name})',
      // Real-device signals the backend requires (_assert_real_device_signals):
      // the app keeps its session (the web's "cookies"), is not driven by
      // WebDriver, and reports the phone's processor count.
      'cookie_enabled': true,
      'webdriver': false,
      'hardware_concurrency': kIsWeb ? 1 : Platform.numberOfProcessors,
      'max_touch_points': 5,
    };
  }

  Future<void> _submit(RegistrationPolicy policy) async {
    final l = AppLocalizations.of(context);
    if (_busy || !(_formKey.currentState?.validate() ?? false)) return;
    if (_birthDate == null) {
      setState(() => _error = l.register_birthDate);
      return;
    }
    if (policy.phoneRequired && _idToken == null) {
      setState(() => _error = l.register_verifyPhoneFirst);
      return;
    }
    if (!_consent) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(sessionProvider.notifier).register(
            RegistrationForm(
              username: normalizeUsername(_username.text),
              name: _name.text,
              email: _email.text,
              password: _password.text,
              birthDate: _birthDate!,
              countryCode: _country.text.trim(),
              phoneNumber: _phone.text.trim(),
              firebaseIdToken: _idToken,
              consentVersion: policy.consentVersion,
              telemetry: _telemetry(context),
              socialRegistrationToken: widget.social?.token,
            ),
          );
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = error.failure == ApiFailure.validation || error.failure == ApiFailure.conflict
            ? error.message
            : error.failure == ApiFailure.rateLimited
                ? l.auth_tooManyAttempts
                : error.failure == ApiFailure.network
                    ? l.app_networkError
                    : l.register_registrationError);
      }
    } on Object {
      if (mounted) setState(() => _error = l.register_registrationError);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _pickBirthDate(RegistrationPolicy policy) async {
    final now = DateTime.now();
    final latest = DateTime(now.year - policy.minimumAge, now.month, now.day);
    final picked = await showDatePicker(
      context: context,
      firstDate: DateTime(now.year - 110),
      lastDate: latest,
      initialDate: _birthDate ?? latest,
      initialEntryMode: DatePickerEntryMode.calendarOnly,
    );
    if (picked != null) setState(() => _birthDate = picked);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final policy = ref.watch(registrationPolicyProvider);
    return Scaffold(
      appBar: AppBar(leading: BackButton(onPressed: () => context.go('/login'))),
      body: policy.when(
        loading: () => Center(child: Text(l.register_checkingPolicy)),
        error: (_, _) => Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(l.register_configurationError),
            const SizedBox(height: 12),
            FilledButton(onPressed: () => ref.invalidate(registrationPolicyProvider), child: Text(l.register_retry)),
          ]),
        ),
        data: (policy) {
          if (!policy.enabled) {
            return Center(child: Padding(padding: const EdgeInsets.all(24), child: Notice(text: l.register_registrationClosed)));
          }
          final locale = Localizations.localeOf(context).toLanguageTag();
          return Form(
            key: _formKey,
            child: AutofillGroup(
              child: FormColumn(
                children: [
                  const Center(child: BrandMark(size: 56)),
                  const SizedBox(height: 16),
                  Text(l.register_title, textAlign: TextAlign.center, style: theme.textTheme.headlineSmall),
                  const SizedBox(height: 20),
                  if (widget.social != null) ...[
                    Notice(
                      key: const Key('register-social-note'),
                      text: l.app_socialSignUpNote(_providerLabel(widget.social!.provider)),
                    ),
                    const SizedBox(height: 12),
                  ],
                  TextFormField(
                    key: const Key('register-name'),
                    controller: _name,
                    enabled: !_busy,
                    autofillHints: const [AutofillHints.name],
                    decoration: InputDecoration(labelText: l.register_name),
                    validator: (v) => (v?.trim().length ?? 0) >= 2 ? null : l.register_name,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    key: const Key('register-username'),
                    controller: _username,
                    enabled: !_busy,
                    autocorrect: false,
                    textDirection: TextDirection.ltr,
                    autofillHints: const [AutofillHints.newUsername],
                    inputFormatters: [LengthLimitingTextInputFormatter(32)],
                    decoration: InputDecoration(labelText: l.register_username, helperText: l.register_usernameRule),
                    validator: (v) => _usernamePattern.hasMatch(normalizeUsername(v ?? '')) ? null : l.register_usernameRule,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    key: const Key('register-email'),
                    controller: _email,
                    enabled: !_busy,
                    // The backend requires the provider's email (SOCIAL_EMAIL_MISMATCH).
                    readOnly: widget.social != null,
                    keyboardType: TextInputType.emailAddress,
                    autocorrect: false,
                    textDirection: TextDirection.ltr,
                    autofillHints: const [AutofillHints.email],
                    decoration: InputDecoration(labelText: l.register_email),
                    validator: (v) => _emailPattern.hasMatch(v?.trim() ?? '') ? null : l.register_email,
                  ),
                  const SizedBox(height: 12),
                  PasswordField(
                    key: const Key('register-password'),
                    controller: _password,
                    label: l.register_password,
                    enabled: !_busy,
                    newPassword: true,
                    validator: (v) => (v?.length ?? 0) >= 12 ? null : l.register_passwordRule,
                  ),
                  const SizedBox(height: 12),
                  PasswordField(
                    key: const Key('register-confirm'),
                    controller: _confirm,
                    label: l.register_confirmPassword,
                    enabled: !_busy,
                    newPassword: true,
                    validator: (v) => v == _password.text ? null : l.register_passwordMismatch,
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    key: const Key('register-birth'),
                    onPressed: _busy ? null : () => _pickBirthDate(policy),
                    icon: const Icon(Icons.cake_outlined),
                    label: Text(_birthDate == null ? l.register_birthDate : DateFormat.yMMMd(locale).format(_birthDate!)),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    key: const Key('register-country'),
                    controller: _country,
                    enabled: !_busy,
                    textCapitalization: TextCapitalization.characters,
                    textDirection: TextDirection.ltr,
                    inputFormatters: [
                      FilteringTextInputFormatter.allow(RegExp('[A-Za-z]')),
                      LengthLimitingTextInputFormatter(2),
                    ],
                    decoration: InputDecoration(labelText: l.register_countryCode, helperText: l.register_countryRule),
                    validator: (v) => (v?.trim().length ?? 0) == 2 ? null : l.register_countryRule,
                  ),
                  const SizedBox(height: 20),
                  Text(l.register_phoneTitle, style: theme.textTheme.titleMedium),
                  const SizedBox(height: 4),
                  Text(
                    policy.phoneRequired ? l.register_phoneRequired : l.register_phoneOptional,
                    style: theme.textTheme.bodySmall,
                  ),
                  const SizedBox(height: 10),
                  TextFormField(
                    key: const Key('register-phone'),
                    controller: _phone,
                    enabled: !_busy && _stage != _PhoneStage.sending,
                    keyboardType: TextInputType.phone,
                    textDirection: TextDirection.ltr,
                    autofillHints: const [AutofillHints.telephoneNumber],
                    inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[+0-9]')), LengthLimitingTextInputFormatter(16)],
                    onChanged: _phoneChanged,
                    decoration: InputDecoration(
                      labelText: l.register_phoneNumber,
                      helperText: l.register_phoneRule,
                      suffixIcon: _stage == _PhoneStage.verified ? const Icon(Icons.verified, color: Color(0xFF2F9E62)) : null,
                    ),
                  ),
                  const SizedBox(height: 10),
                  if (_stage == _PhoneStage.idle || _stage == _PhoneStage.sending)
                    OutlinedButton(
                      key: const Key('register-send-code'),
                      onPressed: _stage == _PhoneStage.sending || _busy ? null : _sendCode,
                      child: Text(l.register_sendCode),
                    ),
                  if (_stage == _PhoneStage.code || _stage == _PhoneStage.confirming) ...[
                    Text(l.app_codeSentTo(_phone.text.trim()), style: theme.textTheme.bodySmall),
                    const SizedBox(height: 8),
                    TextField(
                      key: const Key('register-code'),
                      controller: _code,
                      keyboardType: TextInputType.number,
                      textDirection: TextDirection.ltr,
                      autofillHints: const [AutofillHints.oneTimeCode],
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(8)],
                      decoration: InputDecoration(labelText: l.register_verificationCode),
                    ),
                    const SizedBox(height: 8),
                    OutlinedButton(
                      key: const Key('register-confirm-code'),
                      onPressed: _stage == _PhoneStage.confirming ? null : _confirmCode,
                      child: Text(l.register_confirmCode),
                    ),
                  ],
                  if (_stage == _PhoneStage.verified)
                    Notice(key: const Key('phone-verified'), text: l.register_phoneVerified, tone: NoticeTone.success),
                  if (_phoneError != null) ...[
                    const SizedBox(height: 8),
                    Notice(key: const Key('phone-error'), text: _phoneError!, tone: NoticeTone.error),
                  ],
                  const SizedBox(height: 16),
                  CheckboxListTile(
                    key: const Key('register-consent'),
                    value: _consent,
                    contentPadding: EdgeInsets.zero,
                    controlAffinity: ListTileControlAffinity.leading,
                    onChanged: _busy ? null : (v) => setState(() => _consent = v ?? false),
                    title: Text('${l.register_consentLead} ${l.register_terms} ${l.register_and} ${l.register_privacy}. ${l.register_consentData}',
                        style: theme.textTheme.bodySmall),
                  ),
                  Wrap(spacing: 8, children: [
                    TextButton(
                      onPressed: () => launchUrl(Uri.parse('https://ai.vip-e.net/${Localizations.localeOf(context).languageCode}/legal/terms'),
                          mode: LaunchMode.externalApplication),
                      child: Text(l.register_terms),
                    ),
                    TextButton(
                      onPressed: () => launchUrl(Uri.parse('https://ai.vip-e.net/${Localizations.localeOf(context).languageCode}/legal/privacy'),
                          mode: LaunchMode.externalApplication),
                      child: Text(l.register_privacy),
                    ),
                  ]),
                  if (_error != null) ...[
                    const SizedBox(height: 8),
                    Notice(key: const Key('register-error'), text: _error!, tone: NoticeTone.error),
                  ],
                  const SizedBox(height: 16),
                  FilledButton(
                    key: const Key('register-submit'),
                    onPressed: _busy || !_consent || (policy.phoneRequired && _stage != _PhoneStage.verified)
                        ? null
                        : () => _submit(policy),
                    child: Text(_busy ? l.register_creating : l.register_createAccount),
                  ),
                  const SizedBox(height: 8),
                  TextButton(onPressed: () => context.go('/login'), child: Text('${l.register_hasAccount} ${l.register_signIn}')),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

/// The web build sends visitors to the website's sign-up page (a public page).
Future<void> openWebsiteRegistration(BuildContext context) {
  final language = Localizations.localeOf(context).languageCode;
  return launchUrl(Uri.parse('https://ai.vip-e.net/$language/register'), webOnlyWindowName: '_self');
}
