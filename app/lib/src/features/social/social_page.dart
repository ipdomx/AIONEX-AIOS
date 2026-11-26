import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart' show DateFormat;
import 'package:url_launcher/url_launcher.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_exception.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../three_d/three_d_repository.dart' show sourceImageType;
import '../workspace/workspace_models.dart' show newRequestId;
import 'social_inbox.dart';
import 'social_repository.dart';

/// Picks an image to upload; replaced in tests.
typedef SocialImagePicker = Future<({List<int> bytes, String name})?> Function();

final socialImagePickerProvider = Provider<SocialImagePicker>((ref) => () async {
      final file = await ImagePicker().pickImage(source: ImageSource.gallery, imageQuality: 92);
      if (file == null) return null;
      return (bytes: await file.readAsBytes(), name: file.name);
    });

String socialError(AppLocalizations l, Object error) {
  if (error is! ApiException) return l.socialPublishing_errors_generic;
  return switch (error.statusCode) {
    409 => l.socialPublishing_errors_conflict,
    413 => l.socialPublishing_errors_mediaTooLarge,
    415 => l.socialPublishing_errors_mediaType,
    422 => error.message.isNotEmpty ? error.message : l.socialPublishing_errors_validation,
    429 => l.socialPublishing_errors_rateLimited,
    _ => l.socialPublishing_errors_generic,
  };
}

String postStatusLabel(AppLocalizations l, String s) => switch (s) {
      'draft' => l.socialPublishing_statuses_draft,
      'scheduled' => l.socialPublishing_statuses_scheduled,
      'publishing' => l.socialPublishing_statuses_publishing,
      'published' => l.socialPublishing_statuses_published,
      'partially_failed' => l.socialPublishing_statuses_partially_failed,
      'failed' => l.socialPublishing_statuses_failed,
      'canceled' => l.socialPublishing_statuses_canceled,
      _ => s,
    };

String targetStatusLabel(AppLocalizations l, String s) => switch (s) {
      'pending' => l.socialPublishing_targetStatuses_pending,
      'publishing' => l.socialPublishing_targetStatuses_publishing,
      'retry_wait' => l.socialPublishing_targetStatuses_retry_wait,
      'published' => l.socialPublishing_targetStatuses_published,
      'failed' => l.socialPublishing_targetStatuses_failed,
      'canceled' => l.socialPublishing_targetStatuses_canceled,
      _ => s,
    };

String healthLabel(AppLocalizations l, String s) => switch (s) {
      'healthy' => l.social_health_healthy,
      'degraded' => l.social_health_degraded,
      'expiring' => l.social_health_expiring,
      'expired' => l.social_health_expired,
      'invalid' => l.social_health_invalid,
      'revoked' => l.social_health_revoked,
      'error' => l.social_health_error,
      _ => l.social_health_unknown,
    };

String issueLabel(AppLocalizations l, String code) => switch (code) {
      'account_disconnected' => l.socialPublishing_issues_account_disconnected,
      'account_reconnect_required' => l.socialPublishing_issues_account_reconnect_required,
      'instagram_requires_media' => l.socialPublishing_issues_instagram_requires_media,
      'instagram_caption_too_long' => l.socialPublishing_issues_instagram_caption_too_long,
      'instagram_too_many_hashtags' => l.socialPublishing_issues_instagram_too_many_hashtags,
      'instagram_too_many_mentions' => l.socialPublishing_issues_instagram_too_many_mentions,
      'instagram_image_must_be_jpeg' => l.socialPublishing_issues_instagram_image_must_be_jpeg,
      'instagram_image_too_large' => l.socialPublishing_issues_instagram_image_too_large,
      'instagram_aspect_ratio_out_of_range' => l.socialPublishing_issues_instagram_aspect_ratio_out_of_range,
      'instagram_links_not_clickable' => l.socialPublishing_issues_instagram_links_not_clickable,
      'instagram_image_downscaled' => l.socialPublishing_issues_instagram_image_downscaled,
      'instagram_image_upscaled' => l.socialPublishing_issues_instagram_image_upscaled,
      'facebook_text_too_long' => l.socialPublishing_issues_facebook_text_too_long,
      'facebook_image_too_large' => l.socialPublishing_issues_facebook_image_too_large,
      'facebook_image_type_unsupported' => l.socialPublishing_issues_facebook_image_type_unsupported,
      'image_post_needs_one_image' => l.socialPublishing_issues_image_post_needs_one_image,
      'image_dimensions_unknown' => l.socialPublishing_issues_image_dimensions_unknown,
      'link_invalid' => l.socialPublishing_issues_link_invalid,
      'link_post_has_media' => l.socialPublishing_issues_link_post_has_media,
      'media_not_found' => l.socialPublishing_issues_media_not_found,
      'text_post_has_media' => l.socialPublishing_issues_text_post_has_media,
      'text_post_needs_text' => l.socialPublishing_issues_text_post_needs_text,
      'publish_outcome_unknown' => l.socialPublishing_issues_publish_outcome_unknown,
      'worker_lease_expired' => l.socialPublishing_issues_worker_lease_expired,
      _ => l.socialPublishing_issues_unknown(code),
    };

/// Facebook Pages and Instagram accounts: connected accounts, compose, calendar.
class SocialPage extends ConsumerStatefulWidget {
  const SocialPage({super.key, this.pollInterval = const Duration(seconds: 5)});

  final Duration pollInterval;

  @override
  ConsumerState<SocialPage> createState() => _SocialPageState();
}

class _SocialPageState extends ConsumerState<SocialPage> with WidgetsBindingObserver {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _timer = Timer.periodic(widget.pollInterval, (_) {
      final posts = ref.read(socialPostsProvider).value;
      if (posts != null && posts.any((p) => p.status == 'publishing')) ref.invalidate(socialPostsProvider);
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    super.dispose();
  }

  // Coming back from connecting an account on the website.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) ref.invalidate(socialAccountsProvider);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return DefaultTabController(
      length: 4,
      child: Scaffold(
        appBar: AppBar(
          title: Text(l.app_social),
          actions: [
            IconButton(
              tooltip: l.socialPublishing_calendar_refresh,
              icon: const Icon(Icons.refresh),
              onPressed: () {
                ref.invalidate(socialAccountsProvider);
                ref.invalidate(socialPostsProvider);
                ref.invalidate(socialMediaProvider);
              },
            ),
          ],
          bottom: TabBar(isScrollable: true, tabAlignment: TabAlignment.start, tabs: [
            Tab(text: l.socialPublishing_nav_accounts),
            Tab(text: l.socialPublishing_nav_compose),
            Tab(text: l.socialPublishing_nav_calendar),
            Tab(text: l.socialInbox_eyebrow),
          ]),
        ),
        body: const TabBarView(children: [_AccountsTab(), _ComposeTab(), _CalendarTab(), InboxTab()]),
      ),
    );
  }
}

class _AccountsTab extends ConsumerWidget {
  const _AccountsTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    Future<void> act(Future<void> Function() action) async {
      final messenger = ScaffoldMessenger.of(context);
      try {
        await action();
      } on Object catch (error) {
        messenger.showSnackBar(SnackBar(content: Text(socialError(l, error))));
      }
      ref.invalidate(socialAccountsProvider);
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(l.social_description, style: theme.textTheme.bodySmall),
        const SizedBox(height: 10),
        Notice(text: l.app_socialConnectOnWebsite),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: TextButton.icon(
            key: const Key('social-open-website'),
            icon: const Icon(Icons.open_in_new),
            label: Text(l.app_socialOpenWebsite),
            onPressed: () => launchUrl(
              Uri.parse('https://ai.vip-e.net/${Localizations.localeOf(context).languageCode}/social'),
              mode: LaunchMode.externalApplication,
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(l.social_accounts_title, style: theme.textTheme.titleMedium),
        AsyncView(
          value: ref.watch(socialAccountsProvider),
          onRetry: () => ref.invalidate(socialAccountsProvider),
          builder: (accounts) => accounts.isEmpty
              ? Text(l.social_accounts_empty, style: theme.textTheme.bodySmall)
              : Column(children: [
                  for (final a in accounts)
                    Card(
                      key: Key('social-account-${a.id}'),
                      child: ListTile(
                        leading: Icon(a.provider == 'instagram' ? Icons.camera_alt_outlined : Icons.flag_outlined),
                        title: Text(a.displayName),
                        subtitle: Text([
                          a.provider == 'instagram' ? l.social_kinds_instagram : l.social_kinds_page,
                          healthLabel(l, a.healthState),
                          l.social_accounts_lastChecked(a.lastHealthAt == null ? l.social_accounts_never : format.format(a.lastHealthAt!.toLocal())),
                        ].join(' · ')),
                        trailing: PopupMenuButton<String>(
                          key: Key('social-account-menu-${a.id}'),
                          onSelected: (v) async {
                            if (v == 'health') {
                              await act(() => ref.read(socialRepositoryProvider).checkHealth(a.id));
                              return;
                            }
                            if (v == 'disconnect' && context.mounted) {
                              final ok = await showDialog<bool>(
                                context: context,
                                builder: (context) => AlertDialog(
                                  content: Text(l.social_accounts_confirmDisconnect),
                                  actions: [
                                    TextButton(onPressed: () => Navigator.pop(context, false), child: Text(l.projects_cancel)),
                                    FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(l.social_accounts_disconnect)),
                                  ],
                                ),
                              );
                              if (ok == true) await act(() => ref.read(socialRepositoryProvider).disconnect(a.id));
                            }
                          },
                          itemBuilder: (_) => [
                            PopupMenuItem(value: 'health', child: Text(l.social_accounts_checkHealth)),
                            PopupMenuItem(value: 'disconnect', child: Text(l.social_accounts_disconnect)),
                          ],
                        ),
                      ),
                    ),
                ]),
        ),
      ],
    );
  }
}

class _ComposeTab extends ConsumerStatefulWidget {
  const _ComposeTab();

  @override
  ConsumerState<_ComposeTab> createState() => _ComposeTabState();
}

class _ComposeTabState extends ConsumerState<_ComposeTab> {
  final _caption = TextEditingController();
  final _link = TextEditingController();
  String _type = 'text';
  final Set<String> _accounts = {};
  final List<SocialMedia> _media = [];
  SocialValidation? _check;
  String? _error;
  bool _busy = false;
  DateTime? _scheduleAt;
  // One key per composed post: a retried tap never creates a second post.
  String _requestId = newRequestId();

  @override
  void dispose() {
    _caption.dispose();
    _link.dispose();
    super.dispose();
  }

  SocialDraft get _draft => SocialDraft(
        postType: _type,
        caption: _caption.text,
        link: _type == 'link' ? _link.text : null,
        accountIds: _accounts.toList(),
        media: [for (final m in _media) m.ref],
        timezone: 'UTC',
      );

  void _changed() => setState(() => _check = null);

  Future<void> _upload() async {
    final l = AppLocalizations.of(context);
    final picked = await ref.read(socialImagePickerProvider)();
    if (picked == null || !mounted) return;
    final type = sourceImageType(picked.bytes);
    if (type == null) {
      setState(() => _error = l.socialPublishing_errors_mediaType);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final item = await ref.read(socialRepositoryProvider).upload(picked.bytes, filename: picked.name, mediaType: type);
      ref.invalidate(socialMediaProvider);
      setState(() {
        _media
          ..clear()
          ..add(item);
        _type = 'image';
        _check = null;
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = socialError(l, error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _pickSchedule() async {
    final now = DateTime.now();
    final date = await showDatePicker(context: context, firstDate: now, lastDate: now.add(const Duration(days: 180)), initialDate: now);
    if (date == null || !mounted) return;
    final time = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(now.add(const Duration(hours: 1))));
    if (time == null) return;
    setState(() => _scheduleAt = DateTime(date.year, date.month, date.day, time.hour, time.minute));
  }

  /// Validate, then create the post and publish it now, schedule it, or keep it as a draft.
  Future<void> _submit(String mode) async {
    final l = AppLocalizations.of(context);
    if (_busy) return;
    if (mode == 'schedule') {
      final at = _scheduleAt;
      final problem = at == null
          ? l.socialPublishing_errors_scheduleMissing
          : at.isBefore(DateTime.now().add(const Duration(minutes: 1)))
              ? l.socialPublishing_errors_scheduleInPast
              : null;
      if (problem != null) {
        setState(() => _error = problem);
        return;
      }
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final repo = ref.read(socialRepositoryProvider);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final check = await repo.validate(_draft);
      setState(() => _check = check);
      if (!check.valid && mode != 'draft') {
        setState(() => _error = l.socialPublishing_composer_fixErrors);
        return;
      }
      final post = await repo.create(_draft, idempotencyKey: _requestId);
      final String done;
      if (mode == 'now') {
        await repo.publishNow(post.id);
        done = l.socialPublishing_composer_queued;
      } else if (mode == 'schedule') {
        await repo.schedule(post.id, _scheduleAt!, 'UTC');
        done = l.socialPublishing_composer_scheduled;
      } else {
        done = l.socialPublishing_composer_saved;
      }
      ref.invalidate(socialPostsProvider);
      messenger.showSnackBar(SnackBar(content: Text(done)));
      setState(() {
        _caption.clear();
        _link.clear();
        _media.clear();
        _type = 'text';
        _check = null;
        _scheduleAt = null;
        _requestId = newRequestId();
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = socialError(l, error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final accounts = ref.watch(socialAccountsProvider);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    final tags = RegExp(r'#\w+').allMatches(_caption.text).length;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(l.socialPublishing_composer_description, style: theme.textTheme.bodySmall),
        const SizedBox(height: 12),
        Text(l.socialPublishing_composer_accounts, style: theme.textTheme.titleSmall),
        AsyncView(
          value: accounts,
          onRetry: () => ref.invalidate(socialAccountsProvider),
          builder: (rows) => rows.isEmpty
              ? Text(l.socialPublishing_composer_noAccounts, style: theme.textTheme.bodySmall)
              : Wrap(spacing: 6, runSpacing: 6, children: [
                  for (final a in rows)
                    FilterChip(
                      key: Key('compose-account-${a.id}'),
                      label: Text(a.usable ? a.displayName : '${a.displayName} · ${l.socialPublishing_composer_reconnect}'),
                      avatar: Icon(a.provider == 'instagram' ? Icons.camera_alt_outlined : Icons.flag_outlined, size: 16),
                      selected: _accounts.contains(a.id),
                      onSelected: !a.usable || _busy
                          ? null
                          : (on) {
                              setState(() => on ? _accounts.add(a.id) : _accounts.remove(a.id));
                              _changed();
                            },
                    ),
                ]),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          key: const Key('compose-type'),
          isExpanded: true,
          initialValue: _type,
          decoration: InputDecoration(labelText: l.socialPublishing_composer_postType),
          items: [
            DropdownMenuItem(value: 'text', child: Text(l.socialPublishing_types_text)),
            DropdownMenuItem(value: 'link', child: Text(l.socialPublishing_types_link)),
            DropdownMenuItem(value: 'image', child: Text(l.socialPublishing_types_image)),
          ],
          onChanged: _busy
              ? null
              : (v) {
                  setState(() {
                    _type = v ?? 'text';
                    if (_type != 'image') _media.clear();
                  });
                  _changed();
                },
        ),
        const SizedBox(height: 10),
        TextField(
          key: const Key('compose-caption'),
          controller: _caption,
          enabled: !_busy,
          minLines: 3,
          maxLines: 8,
          decoration: InputDecoration(labelText: l.socialPublishing_composer_caption, hintText: l.socialPublishing_composer_captionPlaceholder, alignLabelWithHint: true),
          onChanged: (_) => _changed(),
        ),
        Text(l.socialPublishing_composer_counter(_caption.text.characters.length, 2200, tags, 30), style: theme.textTheme.bodySmall),
        if (_type == 'link') ...[
          const SizedBox(height: 8),
          TextField(
            key: const Key('compose-link'),
            controller: _link,
            enabled: !_busy,
            keyboardType: TextInputType.url,
            decoration: InputDecoration(labelText: l.socialPublishing_composer_link),
            onChanged: (_) => _changed(),
          ),
        ],
        if (_type == 'image') ...[
          const SizedBox(height: 8),
          Text(l.socialPublishing_composer_mediaHint, style: theme.textTheme.bodySmall),
          Wrap(spacing: 6, children: [
            for (final m in _media)
              InputChip(label: Text(m.filename), onDeleted: _busy ? null : () => setState(() => _media.remove(m))),
            OutlinedButton.icon(
              key: const Key('compose-upload'),
              style: OutlinedButton.styleFrom(minimumSize: const Size(0, 40)),
              onPressed: _busy ? null : _upload,
              icon: const Icon(Icons.upload),
              label: Text(l.socialPublishing_composer_upload),
            ),
          ]),
        ],
        if (_check != null && _check!.issues.isNotEmpty) ...[
          const SizedBox(height: 10),
          for (final issue in _check!.issues)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                '${issue.blocking ? l.socialPublishing_composer_blocking : l.socialPublishing_composer_warning} · ${issue.provider}: ${issueLabel(l, issue.code)}',
                style: TextStyle(color: issue.blocking ? theme.colorScheme.error : theme.colorScheme.onSurfaceVariant),
              ),
            ),
        ],
        if (_error != null) ...[
          const SizedBox(height: 8),
          Notice(key: const Key('compose-error'), text: _error!, tone: NoticeTone.error),
        ],
        const SizedBox(height: 12),
        Text(l.socialPublishing_composer_honesty, style: theme.textTheme.bodySmall),
        const SizedBox(height: 10),
        FilledButton.icon(
          key: const Key('compose-publish'),
          onPressed: _busy || _accounts.isEmpty ? null : () => _submit('now'),
          icon: const Icon(Icons.send),
          label: Text(l.socialPublishing_composer_publishNow(_accounts.length)),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          key: const Key('compose-pick-time'),
          onPressed: _busy ? null : _pickSchedule,
          icon: const Icon(Icons.schedule),
          label: Text(_scheduleAt == null ? l.socialPublishing_composer_when : format.format(_scheduleAt!)),
        ),
        if (_scheduleAt != null)
          TextButton(
            key: const Key('compose-schedule'),
            onPressed: _busy || _accounts.isEmpty ? null : () => _submit('schedule'),
            child: Text(l.socialPublishing_composer_schedule),
          ),
        TextButton(
          key: const Key('compose-draft'),
          onPressed: _busy || _accounts.isEmpty ? null : () => _submit('draft'),
          child: Text(l.socialPublishing_composer_saveDraft),
        ),
      ],
    );
  }
}

class _CalendarTab extends ConsumerWidget {
  const _CalendarTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    final repo = ref.read(socialRepositoryProvider);
    Future<void> act(Future<void> Function() action) async {
      final messenger = ScaffoldMessenger.of(context);
      try {
        await action();
      } on Object catch (error) {
        messenger.showSnackBar(SnackBar(content: Text(socialError(l, error))));
      }
      ref.invalidate(socialPostsProvider);
    }

    return AsyncView(
      value: ref.watch(socialPostsProvider),
      onRetry: () => ref.invalidate(socialPostsProvider),
      builder: (posts) {
        final drafts = posts.where((p) => p.status == 'draft').toList();
        final dated = posts.where((p) => p.status != 'draft').toList()
          ..sort((a, b) => (b.when ?? b.createdAt ?? DateTime(0)).compareTo(a.when ?? a.createdAt ?? DateTime(0)));
        Widget card(SocialPost p) => Card(
              key: Key('social-post-${p.id}'),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Expanded(
                      child: Text(
                        p.caption.isEmpty ? l.socialPublishing_calendar_noCaption : p.caption,
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    StatusChip(
                      label: postStatusLabel(l, p.status),
                      positive: p.status == 'published',
                      negative: p.status == 'failed' || p.status == 'partially_failed',
                    ),
                  ]),
                  Text(
                    p.when == null ? l.socialPublishing_calendar_unscheduled : l.socialPublishing_calendar_when(format.format(p.when!.toLocal()), p.timezone),
                    style: theme.textTheme.bodySmall,
                  ),
                  for (final t in p.targets)
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Row(children: [
                        Expanded(
                          child: Text(
                            '${t.accountName} · ${targetStatusLabel(l, t.status)} · ${l.socialPublishing_calendar_attempts(t.attempts)}'
                            '${t.errorCode == null ? '' : ' · ${issueLabel(l, t.errorCode!)}'}',
                            style: theme.textTheme.bodySmall,
                          ),
                        ),
                        if (t.permalink != null)
                          IconButton(
                            tooltip: l.socialPublishing_calendar_viewLive,
                            icon: const Icon(Icons.open_in_new, size: 18),
                            onPressed: () {
                              final url = Uri.tryParse(t.permalink!);
                              if (url != null && url.scheme == 'https') launchUrl(url, mode: LaunchMode.externalApplication);
                            },
                          ),
                      ]),
                    ),
                  Wrap(spacing: 4, children: [
                    if (p.canPublish)
                      TextButton(
                        key: Key('post-publish-${p.id}'),
                        onPressed: () => act(() => repo.publishNow(p.id)),
                        child: Text(l.socialPublishing_composer_publishNow(p.targets.length)),
                      ),
                    if (p.canCancel)
                      TextButton(
                        key: Key('post-cancel-${p.id}'),
                        onPressed: () => act(() => repo.cancel(p.id)),
                        child: Text(l.socialPublishing_calendar_cancel),
                      ),
                    if (p.canDelete)
                      TextButton(
                        key: Key('post-delete-${p.id}'),
                        onPressed: () => act(() => repo.delete(p.id)),
                        child: Text(l.socialPublishing_calendar_delete),
                      ),
                  ]),
                ]),
              ),
            );
        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(socialPostsProvider),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(l.socialPublishing_calendar_description, style: theme.textTheme.bodySmall),
              const SizedBox(height: 10),
              Text(l.socialPublishing_calendar_drafts, style: theme.textTheme.titleSmall),
              if (drafts.isEmpty) Text(l.socialPublishing_calendar_noDrafts, style: theme.textTheme.bodySmall),
              for (final p in drafts) card(p),
              const SizedBox(height: 12),
              Text(l.socialPublishing_calendar_title, style: theme.textTheme.titleSmall),
              for (final p in dated) card(p),
            ],
          ),
        );
      },
    );
  }
}
