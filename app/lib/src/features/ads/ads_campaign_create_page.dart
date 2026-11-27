import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart' show DateFormat;

import '../../../l10n/generated/app_localizations.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../social/social_repository.dart';
import 'ads_page.dart';
import 'ads_repository.dart';

const adsObjectives = ['traffic', 'awareness', 'engagement'];
const adsCallsToAction = ['LEARN_MORE', 'SHOP_NOW', 'SIGN_UP', 'CONTACT_US', 'BOOK_TRAVEL', 'DOWNLOAD', 'GET_OFFER'];

String newIdempotencyKey() {
  final random = Random.secure();
  return List.generate(12, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
}

/// Everything the form picks from: ad accounts, Pages, images and published posts.
@immutable
class AdsCreateSources {
  const AdsCreateSources({
    required this.access,
    required this.links,
    required this.pages,
    required this.instagram,
    required this.images,
    required this.posts,
  });

  final AdsAccess access;
  final List<AdAccountLink> links;
  final List<SocialAccount> pages;
  final List<SocialAccount> instagram;
  final List<SocialMedia> images;
  final List<SocialTarget> posts;
}

final adsCreateSourcesProvider = FutureProvider.autoDispose<AdsCreateSources>((ref) async {
  final ads = ref.watch(adsRepositoryProvider);
  final social = ref.watch(socialRepositoryProvider);
  final results = await Future.wait<Object>([
    ads.access(),
    ads.links(),
    social.accounts(),
    social.media(),
    social.posts(),
  ]);
  final accounts = [for (final a in results[2] as List<SocialAccount>) if (a.status == 'active') a];
  return AdsCreateSources(
    access: results[0] as AdsAccess,
    links: results[1] as List<AdAccountLink>,
    pages: [for (final a in accounts) if (a.provider == 'facebook') a],
    instagram: [for (final a in accounts) if (a.provider == 'instagram') a],
    images: [for (final m in results[3] as List<SocialMedia>) if (m.kind == 'image') m],
    posts: [
      for (final p in results[4] as List<SocialPost>)
        for (final t in p.targets)
          if (t.status == 'published' && (t.remotePostId ?? '').isNotEmpty && t.id.isNotEmpty) t,
    ],
  );
});

/// The website's campaign builder: always created PAUSED; activation stays a separate typed step.
class AdsCampaignCreatePage extends ConsumerWidget {
  const AdsCampaignCreatePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(l.ads_create_title)),
      body: AsyncView(
        value: ref.watch(adsCreateSourcesProvider),
        onRetry: () => ref.invalidate(adsCreateSourcesProvider),
        builder: (sources) => _CreateForm(sources: sources),
      ),
    );
  }
}

class _CreateForm extends ConsumerStatefulWidget {
  const _CreateForm({required this.sources});

  final AdsCreateSources sources;

  @override
  ConsumerState<_CreateForm> createState() => _CreateFormState();
}

class _CreateFormState extends ConsumerState<_CreateForm> {
  final _name = TextEditingController();
  final _budget = TextEditingController();
  final _countries = TextEditingController();
  final _ageMin = TextEditingController(text: '18');
  final _ageMax = TextEditingController(text: '65');
  final _message = TextEditingController();
  final _headline = TextEditingController();
  final _url = TextEditingController();
  String _key = newIdempotencyKey();

  late String? _linkId = widget.sources.links.firstOrNull?.id;
  String _objective = 'traffic';
  String _budgetType = 'daily';
  DateTime? _start;
  DateTime? _end;
  String _gender = 'all';
  final Set<String> _platforms = {'facebook', 'instagram'};
  String _source = 'post';
  String? _postId;
  String? _mediaRef;
  String? _pageId;
  String? _instagramId;
  String _cta = 'LEARN_MORE';
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_name, _budget, _countries, _ageMin, _ageMax, _message, _headline, _url]) {
      c.dispose();
    }
    super.dispose();
  }

  AdAccountLink? get _link =>
      widget.sources.links.where((x) => x.id == _linkId).firstOrNull ?? widget.sources.links.firstOrNull;

  Future<void> _pickDate(bool start) async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      firstDate: DateTime(now.year, now.month, now.day),
      lastDate: now.add(const Duration(days: 365 * 2)),
      initialDate: (start ? _start : _end) ?? now,
    );
    if (picked != null) setState(() => start ? _start = picked : _end = picked);
  }

  Future<void> _submit() async {
    final l = AppLocalizations.of(context);
    final link = _link;
    final currency = link?.currency ?? 'USD';
    final amount = toMinor(_budget.text, currency);
    final countries = [
      for (final c in _countries.text.split(','))
        if (RegExp(r'^[A-Z]{2}$').hasMatch(c.trim().toUpperCase())) c.trim().toUpperCase(),
    ];
    final url = _url.text.trim();
    final creativeReady = _source == 'post'
        ? _postId != null
        : _mediaRef != null && _pageId != null && _message.text.trim().isNotEmpty && url.startsWith('https://');
    if (link == null ||
        _name.text.trim().isEmpty ||
        amount == 0 ||
        countries.isEmpty ||
        _platforms.isEmpty ||
        !creativeReady ||
        (_budgetType == 'lifetime' && _end == null)) {
      setState(() => _error = l.ads_create_invalid);
      return;
    }
    final input = <String, Object?>{
      'link_id': link.id,
      'name': _name.text.trim(),
      'objective': _objective,
      'daily_budget_minor': _budgetType == 'daily' ? amount : null,
      'lifetime_budget_minor': _budgetType == 'lifetime' ? amount : null,
      'start_time': _start?.toUtc().toIso8601String(),
      'end_time': _end?.toUtc().toIso8601String(),
      'targeting': {
        'countries': countries,
        'age_min': int.tryParse(_ageMin.text) ?? 18,
        'age_max': int.tryParse(_ageMax.text) ?? 65,
        'genders': _gender == 'all' ? <int>[] : [int.parse(_gender)],
        'publisher_platforms': [
          for (final p in const ['facebook', 'instagram'])
            if (_platforms.contains(p)) p,
        ],
      },
      'creative': _source == 'post'
          ? {'source': 'post', 'post_target_id': _postId}
          : {
              'source': _mediaRef!.startsWith('studio:') ? 'studio' : 'upload',
              'media_ref': _mediaRef,
              'page_account_id': _pageId,
              'instagram_account_id': _instagramId,
              'message': _message.text.trim(),
              'headline': _headline.text.trim(),
              'link_url': url,
              'call_to_action': _cta,
            },
      'client_idempotency_key': _key,
    };
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(adsRepositoryProvider).create(input);
      if (!mounted) return;
      _key = newIdempotencyKey();
      ref.invalidate(adsCampaignsProvider);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.ads_create_created)));
      context.pop();
    } on Object catch (error) {
      if (mounted) setState(() => _error = adsError(l, error));
      // A failed creation may still have left a draft to retry from the list.
      ref.invalidate(adsCampaignsProvider);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final s = widget.sources;
    final currency = _link?.currency ?? 'USD';
    final dates = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag());
    if (!s.access.allowed) {
      return ListView(padding: const EdgeInsets.all(16), children: [Notice(text: l.ads_errors_planRequired)]);
    }
    if (s.links.isEmpty) {
      return ListView(padding: const EdgeInsets.all(16), children: [Notice(text: l.ads_accounts_noLinked)]);
    }
    const gap = SizedBox(height: 12);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(l.ads_create_description, style: theme.textTheme.bodySmall),
        const SizedBox(height: 4),
        Text(
          l.ads_create_caps(moneyMinor(s.access.dailyCapMinor, currency), moneyMinor(s.access.lifetimeCapMinor, currency)),
          style: theme.textTheme.bodySmall,
        ),
        gap,
        TextField(
          key: const Key('create-name'),
          controller: _name,
          enabled: !_busy,
          inputFormatters: [LengthLimitingTextInputFormatter(120)],
          decoration: InputDecoration(labelText: l.ads_create_name),
        ),
        gap,
        DropdownButtonFormField<String>(
          key: const Key('create-link'),
          isExpanded: true,
          initialValue: _link?.id,
          decoration: InputDecoration(labelText: l.ads_dashboard_account),
          items: [for (final x in s.links) DropdownMenuItem(value: x.id, child: Text('${x.name} · ${x.currency}'))],
          onChanged: _busy ? null : (v) => setState(() => _linkId = v),
        ),
        gap,
        DropdownButtonFormField<String>(
          key: const Key('create-objective'),
          isExpanded: true,
          initialValue: _objective,
          decoration: InputDecoration(labelText: l.ads_create_objective),
          items: [
            DropdownMenuItem(value: 'traffic', child: Text(l.ads_objective_traffic)),
            DropdownMenuItem(value: 'awareness', child: Text(l.ads_objective_awareness)),
            DropdownMenuItem(value: 'engagement', child: Text(l.ads_objective_engagement)),
          ],
          onChanged: _busy
              ? null
              : (v) => setState(() {
                    _objective = v ?? 'traffic';
                    // Engagement promotes an existing post only.
                    if (_objective == 'engagement') _source = 'post';
                  }),
        ),
        Text(l.ads_create_objectiveNote, style: theme.textTheme.bodySmall),
        gap,
        Row(
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                key: const Key('create-budget-type'),
                isExpanded: true,
                initialValue: _budgetType,
                decoration: InputDecoration(labelText: l.ads_create_budgetType),
                items: [
                  DropdownMenuItem(value: 'daily', child: Text(l.ads_create_daily)),
                  DropdownMenuItem(value: 'lifetime', child: Text(l.ads_create_lifetime)),
                ],
                onChanged: _busy ? null : (v) => setState(() => _budgetType = v ?? 'daily'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextField(
                key: const Key('create-budget'),
                controller: _budget,
                enabled: !_busy,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(labelText: l.ads_create_budget(currency)),
              ),
            ),
          ],
        ),
        gap,
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            OutlinedButton.icon(
              key: const Key('create-start'),
              onPressed: _busy ? null : () => _pickDate(true),
              icon: const Icon(Icons.event),
              label: Text('${l.ads_create_start}: ${_start == null ? '—' : dates.format(_start!)}'),
            ),
            OutlinedButton.icon(
              key: const Key('create-end'),
              onPressed: _busy ? null : () => _pickDate(false),
              icon: const Icon(Icons.event_busy),
              label: Text('${l.ads_create_end}: ${_end == null ? '—' : dates.format(_end!)}'),
            ),
          ],
        ),
        gap,
        TextField(
          key: const Key('create-countries'),
          controller: _countries,
          enabled: !_busy,
          textCapitalization: TextCapitalization.characters,
          decoration: InputDecoration(labelText: l.ads_create_countries, hintText: 'SA, AE, EG'),
        ),
        gap,
        Row(
          children: [
            Expanded(
              child: TextField(
                key: const Key('create-age-min'),
                controller: _ageMin,
                enabled: !_busy,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(2)],
                decoration: InputDecoration(labelText: l.ads_create_ageMin),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextField(
                key: const Key('create-age-max'),
                controller: _ageMax,
                enabled: !_busy,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(2)],
                decoration: InputDecoration(labelText: l.ads_create_ageMax),
              ),
            ),
          ],
        ),
        gap,
        DropdownButtonFormField<String>(
          key: const Key('create-gender'),
          isExpanded: true,
          initialValue: _gender,
          decoration: InputDecoration(labelText: l.ads_create_gender),
          items: [
            DropdownMenuItem(value: 'all', child: Text(l.ads_create_genderAll)),
            DropdownMenuItem(value: '1', child: Text(l.ads_create_genderMale)),
            DropdownMenuItem(value: '2', child: Text(l.ads_create_genderFemale)),
          ],
          onChanged: _busy ? null : (v) => setState(() => _gender = v ?? 'all'),
        ),
        gap,
        Text(l.ads_create_platforms, style: theme.textTheme.labelLarge),
        Wrap(
          spacing: 8,
          children: [
            for (final p in const ['facebook', 'instagram'])
              FilterChip(
                key: Key('create-platform-$p'),
                label: Text(p == 'facebook' ? 'Facebook' : 'Instagram'),
                selected: _platforms.contains(p),
                onSelected: _busy ? null : (on) => setState(() => on ? _platforms.add(p) : _platforms.remove(p)),
              ),
          ],
        ),
        gap,
        DropdownButtonFormField<String>(
          key: const Key('create-source'),
          isExpanded: true,
          initialValue: _source,
          decoration: InputDecoration(labelText: l.ads_create_creativeSource),
          items: [
            DropdownMenuItem(value: 'post', child: Text(l.ads_source_post)),
            if (_objective != 'engagement') DropdownMenuItem(value: 'upload', child: Text(l.ads_source_upload)),
          ],
          onChanged: _busy ? null : (v) => setState(() => _source = v ?? 'post'),
        ),
        gap,
        if (_source == 'post')
          s.posts.isEmpty
              ? Text(l.ads_create_noPosts, style: theme.textTheme.bodySmall)
              : DropdownButtonFormField<String>(
                  key: const Key('create-post'),
                  initialValue: _postId,
                  isExpanded: true,
                  decoration: InputDecoration(labelText: l.ads_create_post),
                  items: [
                    for (final t in s.posts)
                      DropdownMenuItem(
                        value: t.id,
                        child: Text(
                          [t.accountName, t.provider, if (t.publishedAt != null) dates.format(t.publishedAt!.toLocal())]
                              .join(' · '),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                  onChanged: _busy ? null : (v) => setState(() => _postId = v),
                )
        else ...[
          s.images.isEmpty
              ? Text(l.ads_create_noMedia, style: theme.textTheme.bodySmall)
              : DropdownButtonFormField<String>(
                  key: const Key('create-media'),
                  initialValue: _mediaRef,
                  isExpanded: true,
                  decoration: InputDecoration(labelText: l.ads_create_media),
                  items: [
                    for (final m in s.images)
                      DropdownMenuItem(value: m.ref, child: Text(m.filename, overflow: TextOverflow.ellipsis)),
                  ],
                  onChanged: _busy ? null : (v) => setState(() => _mediaRef = v),
                ),
          gap,
          DropdownButtonFormField<String>(
            key: const Key('create-page'),
            initialValue: _pageId,
            isExpanded: true,
            decoration: InputDecoration(labelText: l.ads_create_page),
            items: [for (final p in s.pages) DropdownMenuItem(value: p.id, child: Text(p.displayName))],
            onChanged: _busy ? null : (v) => setState(() => _pageId = v),
          ),
          gap,
          DropdownButtonFormField<String?>(
            key: const Key('create-instagram'),
            initialValue: _instagramId,
            isExpanded: true,
            decoration: InputDecoration(labelText: l.ads_create_instagram),
            items: [
              DropdownMenuItem<String?>(child: Text(l.ads_none)),
              for (final a in s.instagram) DropdownMenuItem<String?>(value: a.id, child: Text(a.displayName)),
            ],
            onChanged: _busy ? null : (v) => setState(() => _instagramId = v),
          ),
          gap,
          TextField(
            key: const Key('create-message'),
            controller: _message,
            enabled: !_busy,
            minLines: 2,
            maxLines: 5,
            inputFormatters: [LengthLimitingTextInputFormatter(2000)],
            decoration: InputDecoration(labelText: l.ads_create_message),
          ),
          gap,
          TextField(
            key: const Key('create-headline'),
            controller: _headline,
            enabled: !_busy,
            inputFormatters: [LengthLimitingTextInputFormatter(255)],
            decoration: InputDecoration(labelText: l.ads_create_headline),
          ),
          gap,
          TextField(
            key: const Key('create-url'),
            controller: _url,
            enabled: !_busy,
            keyboardType: TextInputType.url,
            textDirection: TextDirection.ltr,
            decoration: InputDecoration(labelText: l.ads_create_link, hintText: 'https://'),
          ),
          gap,
          DropdownButtonFormField<String>(
            key: const Key('create-cta'),
            isExpanded: true,
            initialValue: _cta,
            decoration: InputDecoration(labelText: l.ads_create_cta),
            items: [
              for (final c in adsCallsToAction) DropdownMenuItem(value: c, child: Text(c.replaceAll('_', ' '))),
            ],
            onChanged: _busy ? null : (v) => setState(() => _cta = v ?? 'LEARN_MORE'),
          ),
        ],
        if (_error != null) ...[
          gap,
          Text(_error!, key: const Key('create-error'), style: TextStyle(color: theme.colorScheme.error)),
        ],
        const SizedBox(height: 16),
        FilledButton.icon(
          key: const Key('create-submit'),
          onPressed: _busy ? null : _submit,
          icon: const Icon(Icons.send_outlined),
          label: Text(_busy ? l.ads_create_submitting : l.ads_create_submit),
        ),
      ],
    );
  }
}
