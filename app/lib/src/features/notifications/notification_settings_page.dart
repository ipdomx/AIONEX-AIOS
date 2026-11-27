import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_client.dart';
import '../../core/providers.dart';
import '../../widgets/async_view.dart';
import '../../widgets/error_text.dart';
import '../../widgets/notice.dart';

/// One delivery channel and whether the platform can use it right now.
@immutable
class ChannelReadiness {
  const ChannelReadiness({required this.id, required this.name, required this.ready, required this.ownerOnly});

  final String id;
  final String name;
  final bool ready;
  final bool ownerOnly;

  factory ChannelReadiness.fromJson(Map<String, Object?> json) => ChannelReadiness(
        id: (json['id'] as String?) ?? '',
        name: (json['name'] as String?) ?? (json['id'] as String?) ?? '',
        ready: json['ready'] == true,
        ownerOnly: json['owner_only'] == true,
      );
}

/// A registered address (email, phone push token, WhatsApp). Only the masked form comes back.
@immutable
class ContactEndpoint {
  const ContactEndpoint({
    required this.id,
    required this.channel,
    required this.label,
    required this.maskedAddress,
    required this.verified,
  });

  final String id;
  final String channel;
  final String label;
  final String maskedAddress;
  final bool verified;

  factory ContactEndpoint.fromJson(Map<String, Object?> json) => ContactEndpoint(
        id: (json['id'] as String?) ?? '',
        channel: (json['channel'] as String?) ?? '',
        label: (json['label'] as String?) ?? '',
        maskedAddress: (json['masked_address'] as String?) ?? '',
        verified: json['verified'] == true,
      );
}

/// The account-wide preference (category "*"), as the website edits it.
@immutable
class DeliveryPreference {
  const DeliveryPreference({
    required this.category,
    required this.enabled,
    required this.channels,
    required this.minimumSeverity,
    required this.quietHoursStart,
    required this.quietHoursEnd,
    required this.timezone,
    required this.digestMode,
  });

  final String category;
  final bool enabled;
  final Set<String> channels;
  final String minimumSeverity;
  final String? quietHoursStart;
  final String? quietHoursEnd;
  final String timezone;
  final String digestMode;

  factory DeliveryPreference.fromJson(Map<String, Object?> json) {
    final channels = json['channels'];
    return DeliveryPreference(
      category: (json['category'] as String?) ?? '*',
      enabled: json['enabled'] != false,
      channels: {
        'in_app',
        if (channels is List)
          for (final c in channels)
            if (c is String) c,
      },
      minimumSeverity: (json['minimum_severity'] as String?) ?? 'info',
      quietHoursStart: json['quiet_hours_start'] as String?,
      quietHoursEnd: json['quiet_hours_end'] as String?,
      timezone: (json['timezone'] as String?) ?? 'UTC',
      digestMode: (json['digest_mode'] as String?) ?? 'immediate',
    );
  }

  DeliveryPreference copyWith({Set<String>? channels, String? minimumSeverity}) => DeliveryPreference(
        category: category,
        enabled: enabled,
        channels: channels ?? this.channels,
        minimumSeverity: minimumSeverity ?? this.minimumSeverity,
        quietHoursStart: quietHoursStart,
        quietHoursEnd: quietHoursEnd,
        timezone: timezone,
        digestMode: digestMode,
      );

  Map<String, Object?> toJson() => {
        'category': category,
        'enabled': enabled,
        // In-app is always on, as on the website.
        'channels': ['in_app', ...channels.where((c) => c != 'in_app')],
        'minimum_severity': minimumSeverity,
        'quiet_hours_start': quietHoursStart,
        'quiet_hours_end': quietHoursEnd,
        'timezone': timezone,
        'digest_mode': digestMode,
      };
}

@immutable
class TelegramStatus {
  const TelegramStatus({required this.configured, required this.linked, this.botUsername, this.telegramUsername});

  final bool configured;
  final bool linked;
  final String? botUsername;
  final String? telegramUsername;

  factory TelegramStatus.fromJson(Map<String, Object?> json) => TelegramStatus(
        configured: json['configured'] == true,
        linked: json['linked'] == true && json['link_current'] != false,
        botUsername: json['bot_username'] as String?,
        telegramUsername: json['telegram_username'] as String?,
      );
}

@immutable
class TelegramChallenge {
  const TelegramChallenge({required this.code, this.deepLink});

  final String code;
  final Uri? deepLink;

  factory TelegramChallenge.fromJson(Map<String, Object?> json) {
    final link = Uri.tryParse((json['deep_link'] as String?) ?? '');
    return TelegramChallenge(
      code: (json['code'] as String?) ?? '',
      // Only Telegram's own links are opened.
      deepLink: link != null && link.scheme == 'https' && link.host == 't.me' ? link : null,
    );
  }
}

@immutable
class NotificationSettings {
  const NotificationSettings({
    required this.channels,
    required this.endpoints,
    required this.preference,
    required this.telegram,
  });

  final List<ChannelReadiness> channels;
  final List<ContactEndpoint> endpoints;
  final DeliveryPreference? preference;
  final TelegramStatus telegram;
}

class NotificationSettingsRepository {
  NotificationSettingsRepository(this._api);

  final ApiClient _api;

  Future<NotificationSettings> load() async {
    final results = await Future.wait([
      _api.getList('/communications/channels'),
      _api.getList('/communications/endpoints'),
      _api.getList('/communications/preferences'),
      _api.getJson('/telegram/status'),
    ]);
    Iterable<Map<String, Object?>> maps(Object? list) =>
        (list as List).whereType<Map<Object?, Object?>>().map((m) => m.cast<String, Object?>());
    final preferences = maps(results[2]).map(DeliveryPreference.fromJson).toList();
    return NotificationSettings(
      channels: [
        for (final c in maps(results[0]).map(ChannelReadiness.fromJson))
          if (!c.ownerOnly && c.id.isNotEmpty) c,
      ],
      endpoints: maps(results[1]).map(ContactEndpoint.fromJson).toList(),
      preference: preferences.where((p) => p.category == '*').firstOrNull ?? preferences.firstOrNull,
      telegram: TelegramStatus.fromJson(results[3] as Map<String, Object?>),
    );
  }

  Future<DeliveryPreference> savePreference(DeliveryPreference preference) async =>
      DeliveryPreference.fromJson(await _api.putJson('/communications/preferences', body: preference.toJson()));

  Future<ContactEndpoint> addEndpoint({required String channel, required String address, required String label}) async =>
      ContactEndpoint.fromJson(await _api.postJson(
        '/communications/endpoints',
        body: {'channel': channel, 'address': address, 'label': label},
        retry: false,
      ));

  Future<void> removeEndpoint(String id) => _api.deleteJson('/communications/endpoints/${Uri.encodeComponent(id)}');

  Future<TelegramChallenge> telegramChallenge() async =>
      TelegramChallenge.fromJson(await _api.postJson('/telegram/link-challenge', retry: false));

  Future<void> telegramUnlink() => _api.deleteJson('/telegram/link');
}

final notificationSettingsRepositoryProvider = Provider<NotificationSettingsRepository>(
  (ref) => NotificationSettingsRepository(ref.watch(apiClientProvider)),
);

final notificationSettingsProvider = FutureProvider.autoDispose<NotificationSettings>(
  (ref) => ref.watch(notificationSettingsRepositoryProvider).load(),
);

/// Channels, severity, contact addresses and the Telegram link (the website's notifications settings).
class NotificationSettingsPage extends ConsumerWidget {
  const NotificationSettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final settings = ref.watch(notificationSettingsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(l.app_notificationSettings)),
      body: AsyncView(
        value: settings,
        onRetry: () => ref.invalidate(notificationSettingsProvider),
        builder: (data) => RefreshIndicator(
          onRefresh: () => ref.refresh(notificationSettingsProvider.future),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (data.preference != null) _PreferenceCard(channels: data.channels, initial: data.preference!),
              const SizedBox(height: 12),
              _TelegramCard(status: data.telegram),
              const SizedBox(height: 12),
              _EndpointsCard(
                endpoints: data.endpoints,
                // Typed-in addresses: only channels the server offers this user (WhatsApp is owner-only today).
                channels: [
                  for (final c in data.channels)
                    if (c.id == 'email' || c.id == 'whatsapp') c.id,
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

void _snack(BuildContext context, String text) {
  ScaffoldMessenger.of(context)
    ..clearSnackBars()
    ..showSnackBar(SnackBar(content: Text(text)));
}

class _PreferenceCard extends ConsumerStatefulWidget {
  const _PreferenceCard({required this.channels, required this.initial});

  final List<ChannelReadiness> channels;
  final DeliveryPreference initial;

  @override
  ConsumerState<_PreferenceCard> createState() => _PreferenceCardState();
}

class _PreferenceCardState extends ConsumerState<_PreferenceCard> {
  late DeliveryPreference _preference = widget.initial;
  bool _saving = false;

  Future<void> _save() async {
    final l = AppLocalizations.of(context);
    setState(() => _saving = true);
    try {
      final saved = await ref.read(notificationSettingsRepositoryProvider).savePreference(_preference);
      if (!mounted) return;
      setState(() => _preference = saved);
      _snack(context, l.notifications_preferencesSaved);
    } on Object catch (error) {
      if (mounted) _snack(context, describeError(l, error));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(l.notifications_preferences, style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            for (final channel in widget.channels)
              CheckboxListTile(
                key: Key('pref-channel-${channel.id}'),
                contentPadding: EdgeInsets.zero,
                title: Text(channel.name),
                subtitle: Text(channel.ready ? l.notifications_ready : l.notifications_notConfigured),
                value: _preference.channels.contains(channel.id),
                onChanged: channel.id == 'in_app' || _saving
                    ? null
                    : (on) => setState(() {
                          final next = {..._preference.channels};
                          on == true ? next.add(channel.id) : next.remove(channel.id);
                          _preference = _preference.copyWith(channels: next);
                        }),
              ),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              key: const Key('pref-severity'),
              initialValue: const {'info', 'warning', 'critical'}.contains(_preference.minimumSeverity)
                  ? _preference.minimumSeverity
                  : 'info',
              decoration: InputDecoration(labelText: l.notifications_minimumSeverity),
              items: [
                DropdownMenuItem(value: 'info', child: Text(l.notifications_severity_info)),
                DropdownMenuItem(value: 'warning', child: Text(l.notifications_severity_warning)),
                DropdownMenuItem(value: 'critical', child: Text(l.notifications_severity_critical)),
              ],
              onChanged: _saving
                  ? null
                  : (value) => setState(() => _preference = _preference.copyWith(minimumSeverity: value)),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              key: const Key('pref-save'),
              onPressed: _saving ? null : _save,
              icon: const Icon(Icons.save_outlined),
              label: Text(l.notifications_savePreferences),
            ),
          ],
        ),
      ),
    );
  }
}

class _TelegramCard extends ConsumerStatefulWidget {
  const _TelegramCard({required this.status});

  final TelegramStatus status;

  @override
  ConsumerState<_TelegramCard> createState() => _TelegramCardState();
}

class _TelegramCardState extends ConsumerState<_TelegramCard> {
  TelegramChallenge? _challenge;
  bool _busy = false;

  Future<void> _run(Future<void> Function() action, String failure) async {
    setState(() => _busy = true);
    try {
      await action();
    } on Object {
      if (mounted) _snack(context, failure);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final status = widget.status;
    final repo = ref.read(notificationSettingsRepositoryProvider);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(child: Text(l.notifications_telegramAccount_title, style: theme.textTheme.titleMedium)),
                Chip(
                  key: const Key('telegram-state'),
                  label: Text(
                    status.linked ? l.notifications_telegramAccount_linked : l.notifications_telegramAccount_notLinked,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(l.notifications_telegramAccount_description, style: theme.textTheme.bodySmall),
            if (status.botUsername != null) ...[
              const SizedBox(height: 8),
              Text(l.notifications_telegramAccount_bot(status.botUsername!)),
            ],
            if (!status.configured) ...[
              const SizedBox(height: 12),
              Notice(text: l.notifications_telegramAccount_inactive),
            ],
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton(
                  key: const Key('telegram-create'),
                  style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
                  onPressed: _busy || !status.configured
                      ? null
                      : () => _run(() async {
                            final challenge = await repo.telegramChallenge();
                            if (mounted) setState(() => _challenge = challenge);
                          }, l.notifications_telegramAccount_createError),
                  child: Text(l.notifications_telegramAccount_createLink),
                ),
                OutlinedButton(
                  key: const Key('telegram-refresh'),
                  onPressed: _busy ? null : () => ref.invalidate(notificationSettingsProvider),
                  child: Text(l.notifications_telegramAccount_refresh),
                ),
                if (status.linked)
                  OutlinedButton(
                    key: const Key('telegram-unlink'),
                    onPressed: _busy
                        ? null
                        : () => _run(() async {
                              await repo.telegramUnlink();
                              if (!mounted) return;
                              setState(() => _challenge = null);
                              ref.invalidate(notificationSettingsProvider);
                            }, l.notifications_telegramAccount_unlinkError),
                    child: Text(l.notifications_telegramAccount_unlink),
                  ),
              ],
            ),
            if (_challenge != null) ...[
              const SizedBox(height: 16),
              Text(l.notifications_telegramAccount_oneTimeCode, style: theme.textTheme.labelMedium),
              const SizedBox(height: 4),
              DecoratedBox(
                decoration: BoxDecoration(
                  border: Border.all(color: theme.colorScheme.outlineVariant),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: SelectableText(
                          _challenge!.code,
                          key: const Key('telegram-code'),
                          style: theme.textTheme.titleMedium?.copyWith(fontFamily: 'monospace'),
                        ),
                      ),
                    ),
                    IconButton(
                      key: const Key('telegram-copy'),
                      tooltip: MaterialLocalizations.of(context).copyButtonLabel,
                      icon: const Icon(Icons.copy),
                      onPressed: () async {
                        await Clipboard.setData(ClipboardData(text: _challenge!.code));
                        if (context.mounted) _snack(context, MaterialLocalizations.of(context).copyButtonLabel);
                      },
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 4),
              Text(l.notifications_telegramAccount_expires, style: theme.textTheme.bodySmall),
              if (_challenge!.deepLink != null) ...[
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  key: const Key('telegram-open'),
                  onPressed: () => launchUrl(_challenge!.deepLink!, mode: LaunchMode.externalApplication),
                  icon: const Icon(Icons.send_outlined),
                  label: Text(l.notifications_telegramAccount_openTelegram),
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

class _EndpointsCard extends ConsumerStatefulWidget {
  const _EndpointsCard({required this.endpoints, required this.channels});

  final List<ContactEndpoint> endpoints;
  final List<String> channels;

  @override
  ConsumerState<_EndpointsCard> createState() => _EndpointsCardState();
}

class _EndpointsCardState extends ConsumerState<_EndpointsCard> {
  // Push is registered by the app itself, so only email (and WhatsApp when offered) are typed in.
  final _address = TextEditingController();
  final _label = TextEditingController();
  late String _channel = widget.channels.firstOrNull ?? 'email';
  bool _busy = false;

  @override
  void dispose() {
    _address.dispose();
    _label.dispose();
    super.dispose();
  }

  String _channelName(AppLocalizations l, String id) => switch (id) {
        'email' => l.notifications_channel_email,
        'push' => l.notifications_channel_push,
        'telegram' => l.notifications_channel_telegram,
        'whatsapp' => l.notifications_channel_whatsapp,
        _ => id,
      };

  Future<void> _add() async {
    final l = AppLocalizations.of(context);
    final address = _address.text.trim();
    if (address.isEmpty) return;
    setState(() => _busy = true);
    try {
      final endpoint = await ref.read(notificationSettingsRepositoryProvider).addEndpoint(
            channel: _channel,
            address: address,
            label: _label.text.trim().isEmpty ? l.notifications_primaryEndpoint : _label.text.trim(),
          );
      if (!mounted) return;
      _address.clear();
      _label.clear();
      _snack(context, endpoint.verified ? l.notifications_endpointAdded : l.notifications_endpointPending);
      ref.invalidate(notificationSettingsProvider);
    } on Object {
      if (mounted) _snack(context, l.notifications_endpointError);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove(ContactEndpoint endpoint) async {
    final l = AppLocalizations.of(context);
    setState(() => _busy = true);
    try {
      await ref.read(notificationSettingsRepositoryProvider).removeEndpoint(endpoint.id);
      if (!mounted) return;
      _snack(context, l.notifications_endpointRemoved);
      ref.invalidate(notificationSettingsProvider);
    } on Object catch (error) {
      if (mounted) _snack(context, describeError(l, error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(l.notifications_endpoints, style: theme.textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(l.notifications_endpointsCopy, style: theme.textTheme.bodySmall),
            const SizedBox(height: 12),
            if (widget.endpoints.isEmpty)
              Text(l.notifications_noEndpoints, key: const Key('no-endpoints'))
            else
              for (final endpoint in widget.endpoints)
                ListTile(
                  key: Key('endpoint-${endpoint.id}'),
                  contentPadding: EdgeInsets.zero,
                  title: Text(endpoint.label),
                  subtitle: Text(
                    '${_channelName(l, endpoint.channel)} · ${endpoint.maskedAddress}\n'
                    '${endpoint.verified ? l.notifications_verified : l.notifications_verificationPending}',
                  ),
                  isThreeLine: true,
                  trailing: IconButton(
                    key: Key('endpoint-remove-${endpoint.id}'),
                    tooltip: l.notifications_removeEndpoint,
                    icon: const Icon(Icons.delete_outline),
                    onPressed: _busy ? null : () => _remove(endpoint),
                  ),
                ),
            if (widget.channels.isNotEmpty) ...[
            const Divider(height: 24),
            if (widget.channels.length > 1) ...[
              DropdownButtonFormField<String>(
                key: const Key('endpoint-channel'),
                initialValue: _channel,
                items: [
                  for (final c in widget.channels) DropdownMenuItem(value: c, child: Text(_channelName(l, c))),
                ],
                onChanged: _busy ? null : (value) => setState(() => _channel = value ?? _channel),
              ),
              const SizedBox(height: 8),
            ],
            TextField(
              key: const Key('endpoint-address'),
              controller: _address,
              enabled: !_busy,
              keyboardType: _channel == 'email' ? TextInputType.emailAddress : TextInputType.phone,
              textDirection: TextDirection.ltr,
              inputFormatters: [LengthLimitingTextInputFormatter(320)],
              decoration: InputDecoration(labelText: l.notifications_endpointAddress),
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('endpoint-label'),
              controller: _label,
              enabled: !_busy,
              inputFormatters: [LengthLimitingTextInputFormatter(120)],
              decoration: InputDecoration(labelText: l.notifications_endpointLabel),
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              key: const Key('endpoint-add'),
              onPressed: _busy ? null : _add,
              icon: const Icon(Icons.send_outlined),
              label: Text(l.notifications_addEndpoint),
            ),
            ],
          ],
        ),
      ),
    );
  }
}
