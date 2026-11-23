import 'package:flutter/material.dart';

enum NoticeTone { info, error, success }

/// An inline message that screen readers announce when it appears.
class Notice extends StatelessWidget {
  const Notice({super.key, required this.text, this.tone = NoticeTone.info});

  final String text;
  final NoticeTone tone;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (background, border, foreground) = switch (tone) {
      NoticeTone.error => (scheme.primaryContainer, scheme.primary, scheme.onPrimaryContainer),
      NoticeTone.success => (const Color(0xFF0E2A1B), const Color(0xFF2F9E62), const Color(0xFFB6F2CF)),
      NoticeTone.info => (scheme.surfaceContainerHigh, scheme.outline, scheme.onSurface),
    };
    return Semantics(
      liveRegion: true,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: background,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: border.withValues(alpha: 0.6)),
        ),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Text(text, style: TextStyle(color: foreground)),
        ),
      ),
    );
  }
}

/// A password field with a show/hide toggle and no autocorrect or suggestions.
class PasswordField extends StatefulWidget {
  const PasswordField({
    super.key,
    required this.controller,
    required this.label,
    this.validator,
    this.enabled = true,
    this.newPassword = false,
    this.onSubmitted,
  });

  final TextEditingController controller;
  final String label;
  final String? Function(String?)? validator;
  final bool enabled;
  final bool newPassword;
  final ValueChanged<String>? onSubmitted;

  @override
  State<PasswordField> createState() => _PasswordFieldState();
}

class _PasswordFieldState extends State<PasswordField> {
  bool _obscure = true;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: widget.controller,
      enabled: widget.enabled,
      obscureText: _obscure,
      autocorrect: false,
      enableSuggestions: false,
      textDirection: TextDirection.ltr,
      autofillHints: [widget.newPassword ? AutofillHints.newPassword : AutofillHints.password],
      onFieldSubmitted: widget.onSubmitted,
      validator: widget.validator,
      decoration: InputDecoration(
        labelText: widget.label,
        suffixIcon: IconButton(
          tooltip: widget.label,
          icon: Icon(_obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
          onPressed: () => setState(() => _obscure = !_obscure),
        ),
      ),
    );
  }
}
