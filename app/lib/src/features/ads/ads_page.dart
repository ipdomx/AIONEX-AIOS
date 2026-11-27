import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart' show DateFormat, NumberFormat;
import 'package:url_launcher/url_launcher.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_exception.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import 'ads_planning_tab.dart';
import 'ads_repository.dart';

String adsError(AppLocalizations l, Object error) {
  final code = error is ApiException ? (error.code ?? '') : '';
  return switch (code) {
    'ADS_PLAN_REQUIRED' || 'ADS_DISABLED' => l.ads_errors_planRequired,
    'ads-daily-cap-exceeded' => l.ads_errors_dailyCap,
    'ads-lifetime-cap-exceeded' => l.ads_errors_lifetimeCap,
    'ads-daily-cap-reached' || 'ads-lifetime-cap-reached' || 'ads-spend-cap-not-configured' => l.ads_errors_capReached,
    'activation-confirmation-mismatch' => l.ads_errors_confirmation,
    'ads-activation-disabled-by-owner' => l.ads_errors_activationDisabled,
    'ads-active-campaign-limit' => l.ads_errors_activeLimit,
    'ads-management-permission-not-granted' => l.ads_errors_managePermission,
    'ads-permission-not-granted' => l.ads_errors_readPermission,
    'ad-account-limit-reached' => l.ads_errors_accountLimit,
    'ads-insights-throttled' => l.ads_errors_throttled,
    'ads-no-metrics-yet' => l.ads_errors_noMetrics,
    'ads-recommendation-daily-limit' => l.ads_errors_aiLimit,
    'ai-assistant-unavailable' => l.ads_errors_aiUnavailable,
    'DAILY_MESSAGE_LIMIT' => l.ads_errors_quota,
    'provider-not-configured' => l.ads_errors_notConfigured,
    _ when code.startsWith('meta-ads-') && code.contains('throttled') => l.ads_errors_throttled,
    _ => l.ads_errors_generic,
  };
}

String adsStatusLabel(AppLocalizations l, String s) => switch (s) {
      'draft' => l.ads_status_draft,
      'provisioning' => l.ads_status_provisioning,
      'paused' => l.ads_status_paused,
      'active' => l.ads_status_active,
      'auto_paused' => l.ads_status_auto_paused,
      'failed' => l.ads_status_failed,
      _ => s,
    };

String syncLabel(AppLocalizations l, String s) => switch (s) {
      'ok' => l.ads_sync_ok,
      'syncing' => l.ads_sync_syncing,
      'throttled' => l.ads_sync_throttled,
      'reconnect' => l.ads_sync_reconnect,
      'report_pending' => l.ads_sync_report_pending,
      'error' => l.ads_sync_error,
      _ => l.ads_sync_pending,
    };

void _openWebsite(BuildContext context) => launchUrl(
      Uri.parse('https://ai.vip-e.net/${Localizations.localeOf(context).languageCode}/campaigns'),
      mode: LaunchMode.externalApplication,
    );

/// Meta Ads: performance, AI advice, sync, and pausing or activating campaigns.
class AdsPage extends ConsumerWidget {
  const AdsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final access = ref.watch(adsAccessProvider);
    final planning = ref.watch(paidReadinessProvider);
    // Ads management and owner-reviewed planning are gated separately; the page opens for either.
    final ads = access.value?.allowed == true ? access.value : null;
    final plan = planning.value?.campaignsVisible == true ? planning.value : null;
    final tabs = <(String, Widget)>[
      if (ads != null) ...[
        (l.ads_tabs_dashboard, const _DashboardTab()),
        (l.ads_tabs_accounts, const _AccountsTab()),
        (l.ads_list_title, _CampaignsTab(access: ads)),
      ],
      if (plan != null) (l.ads_tabs_planning, AdsPlanningTab(readiness: plan)),
    ];
    final Widget body;
    if (access.isLoading || planning.isLoading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (tabs.isNotEmpty) {
      body = TabBarView(children: [for (final t in tabs) t.$2]);
    } else if (access.hasError &&
        !(access.error is ApiException && const {402, 403}.contains((access.error! as ApiException).statusCode))) {
      body = ListView(children: [
        Padding(padding: const EdgeInsets.all(16), child: Notice(text: adsError(l, access.error!), tone: NoticeTone.error)),
      ]);
    } else {
      body = ListView(children: [
        EmptyState(icon: Icons.campaign_outlined, title: l.ads_notEntitledTitle, message: l.ads_notEntitledBody),
      ]);
    }
    return DefaultTabController(
      key: ValueKey(tabs.length),
      length: tabs.length,
      child: Scaffold(
        appBar: AppBar(
          title: Text(l.app_ads),
          actions: [
            IconButton(
              tooltip: l.ads_refresh,
              icon: const Icon(Icons.refresh),
              onPressed: () {
                ref.invalidate(adsAccessProvider);
                ref.invalidate(adsLinksProvider);
                ref.invalidate(adsCampaignsProvider);
                ref.invalidate(adsDashboardProvider);
                ref.invalidate(paidReadinessProvider);
                ref.invalidate(paidCampaignsProvider);
              },
            ),
          ],
          bottom: tabs.length > 1
              ? TabBar(
                  // Four tabs (ads + planning) do not fit a phone width; three still do.
                  isScrollable: tabs.length > 3,
                  tabAlignment: tabs.length > 3 ? TabAlignment.start : null,
                  tabs: [for (final t in tabs) Tab(text: t.$1)],
                )
              : null,
        ),
        body: body,
      ),
    );
  }
}

class _DashboardTab extends ConsumerStatefulWidget {
  const _DashboardTab();

  @override
  ConsumerState<_DashboardTab> createState() => _DashboardTabState();
}

class _DashboardTabState extends ConsumerState<_DashboardTab> {
  String? _linkId;
  bool _external = false;
  bool _busy = false;

  Future<void> _recommend(String linkId) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final language = Localizations.localeOf(context).languageCode;
    setState(() => _busy = true);
    try {
      await ref.read(adsRepositoryProvider).recommend(linkId, language: language, externalAllowed: _external);
      ref.invalidate(adsRecommendationsProvider(linkId));
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(adsError(l, error))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final number = NumberFormat.compact(locale: Localizations.localeOf(context).toLanguageTag());
    return AsyncView(
      value: ref.watch(adsLinksProvider),
      onRetry: () => ref.invalidate(adsLinksProvider),
      builder: (links) {
        if (links.isEmpty) {
          return ListView(children: [
            EmptyState(icon: Icons.insights_outlined, title: l.ads_dashboard_noAccount, message: l.app_adsOnWebsite),
          ]);
        }
        final link = links.firstWhere((x) => x.id == _linkId, orElse: () => links.first);
        final dashboard = ref.watch(adsDashboardProvider(link.id));
        final recommendations = ref.watch(adsRecommendationsProvider(link.id));
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            DropdownButtonFormField<String>(
              key: const Key('ads-link'),
              isExpanded: true,
              initialValue: link.id,
              decoration: InputDecoration(labelText: l.ads_dashboard_account),
              items: [for (final x in links) DropdownMenuItem(value: x.id, child: Text('${x.name} (${x.currency})'))],
              onChanged: (v) => setState(() => _linkId = v),
            ),
            const SizedBox(height: 12),
            AsyncView(
              value: dashboard,
              onRetry: () => ref.invalidate(adsDashboardProvider(link.id)),
              builder: (d) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text('${d.from} → ${d.to} · ${l.ads_dashboard_dataSource(d.currency)}', style: theme.textTheme.bodySmall),
                if (!d.hasData) ...[
                  const SizedBox(height: 8),
                  Notice(key: const Key('ads-no-data'), text: l.ads_dashboard_noData),
                ] else ...[
                  const SizedBox(height: 8),
                  Wrap(spacing: 8, runSpacing: 8, children: [
                    for (final (key, label) in [
                      ('spend', l.ads_kpi_spend),
                      ('impressions', l.ads_kpi_impressions),
                      ('clicks', l.ads_kpi_clicks),
                      ('ctr', l.ads_kpi_ctr),
                      ('cpa', l.ads_kpi_cpa),
                      ('roas', l.ads_kpi_roas),
                    ])
                      if (d.kpis[key] != null)
                        SizedBox(
                          width: 150,
                          child: Card(
                            child: Padding(
                              padding: const EdgeInsets.all(10),
                              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                Text(label, style: theme.textTheme.labelSmall),
                                Text(
                                  key == 'spend' || key == 'cpa'
                                      ? money(d.kpis[key]!.value, d.currency)
                                      : d.kpis[key]!.value == null
                                          ? '—'
                                          : number.format(d.kpis[key]!.value),
                                  key: Key('kpi-$key'),
                                  style: theme.textTheme.titleMedium,
                                ),
                                if (d.kpis[key]!.changePct != null)
                                  Text(
                                    '${d.kpis[key]!.changePct! >= 0 ? '▲' : '▼'} ${d.kpis[key]!.changePct!.abs().toStringAsFixed(1)}% ${l.ads_dashboard_vsPrevious}',
                                    style: theme.textTheme.labelSmall,
                                  ),
                              ]),
                            ),
                          ),
                        ),
                  ]),
                  const SizedBox(height: 8),
                  Text(l.ads_dashboard_alerts, style: theme.textTheme.titleSmall),
                  if (d.alerts.isEmpty) Text(l.ads_dashboard_noAlerts, style: theme.textTheme.bodySmall),
                  for (final a in d.alerts) Text('• $a', style: theme.textTheme.bodySmall),
                  const SizedBox(height: 8),
                  Text(l.ads_dashboard_top, style: theme.textTheme.titleSmall),
                  for (final c in d.top)
                    ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      title: Text(c.name),
                      subtitle: Text('${l.ads_kpi_spend} ${money(c.spend, d.currency)} · ${l.ads_kpi_ctr} ${c.ctr?.toStringAsFixed(2) ?? '—'} · '
                          '${l.ads_kpi_roas} ${c.roas?.toStringAsFixed(2) ?? '—'}'),
                    ),
                ],
              ]),
            ),
            const Divider(height: 28),
            Text(l.ads_ai_title, style: theme.textTheme.titleMedium),
            Text(l.ads_ai_description, style: theme.textTheme.bodySmall),
            Text(l.ads_ai_advisory, style: theme.textTheme.bodySmall),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: _external,
              onChanged: (v) => setState(() => _external = v ?? false),
              title: Text(l.ads_ai_externalConsent, style: theme.textTheme.bodySmall),
            ),
            FilledButton.icon(
              key: const Key('ads-recommend'),
              onPressed: _busy ? null : () => _recommend(link.id),
              icon: const Icon(Icons.auto_awesome),
              label: Text(_busy ? l.ads_ai_generating : l.ads_ai_generate),
            ),
            AsyncView(
              value: recommendations,
              onRetry: () => ref.invalidate(adsRecommendationsProvider(link.id)),
              builder: (run) => run == null || run.items.isEmpty
                  ? Text(l.ads_ai_empty, style: theme.textTheme.bodySmall)
                  : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      Text(l.ads_ai_model(run.model), style: theme.textTheme.labelSmall),
                      for (final r in run.items)
                        Card(
                          child: Padding(
                            padding: const EdgeInsets.all(10),
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text(r.title, style: theme.textTheme.titleSmall),
                              Text(r.action),
                              Text(r.rationale, style: theme.textTheme.bodySmall),
                              if (r.evidence.isNotEmpty)
                                Text('${l.ads_ai_basedOn}: ${r.evidence.entries.map((e) => '${e.key} ${e.value}').join(', ')}',
                                    style: theme.textTheme.labelSmall),
                            ]),
                          ),
                        ),
                      if (run.rejected > 0) Text(l.ads_ai_rejected(run.rejected), style: theme.textTheme.bodySmall),
                    ]),
            ),
          ],
        );
      },
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
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Notice(text: l.app_adsOnWebsite),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: TextButton.icon(
            icon: const Icon(Icons.open_in_new),
            label: Text(l.app_socialOpenWebsite),
            onPressed: () => _openWebsite(context),
          ),
        ),
        Text(l.ads_accounts_linkedTitle, style: theme.textTheme.titleMedium),
        AsyncView(
          value: ref.watch(adsLinksProvider),
          onRetry: () => ref.invalidate(adsLinksProvider),
          builder: (links) => links.isEmpty
              ? Text(l.ads_accounts_noLinked, style: theme.textTheme.bodySmall)
              : Column(children: [
                  for (final x in links)
                    Card(
                      key: Key('ads-link-${x.id}'),
                      child: Column(children: [
                        ListTile(
                        title: Text('${x.name} · ${x.currency}'),
                        subtitle: Text([
                          syncLabel(l, x.syncState),
                          l.ads_accounts_lastSync(x.lastSyncAt == null ? l.ads_never : format.format(x.lastSyncAt!.toLocal())),
                          if (x.syncedThrough != null) l.ads_accounts_syncedThrough(x.syncedThrough!),
                          ?x.syncError,
                        ].join(' · ')),
                        trailing: TextButton(
                          key: Key('ads-sync-${x.id}'),
                          onPressed: () async {
                            final messenger = ScaffoldMessenger.of(context);
                            try {
                              await ref.read(adsRepositoryProvider).sync(x.id);
                              messenger.showSnackBar(SnackBar(content: Text(l.ads_accounts_syncRequested)));
                            } on Object catch (error) {
                              messenger.showSnackBar(SnackBar(content: Text(adsError(l, error))));
                            }
                            ref.invalidate(adsLinksProvider);
                          },
                          child: Text(l.ads_accounts_syncNow),
                        ),
                      ),
                        _LinkControls(link: x),
                      ]),
                    ),
                ]),
        ),
      ],
    );
  }
}

class _CampaignsTab extends ConsumerWidget {
  const _CampaignsTab({required this.access});

  final AdsAccess access;

  Future<void> _activate(BuildContext context, WidgetRef ref, AdsCampaign c) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final confirmed = await showDialog<({String phrase, int budget})>(
      context: context,
      builder: (_) => _ActivateDialog(campaign: c, phrase: access.activationPhrase),
    );
    if (confirmed == null) return;
    try {
      await ref.read(adsRepositoryProvider).activate(c.id, phrase: confirmed.phrase, budgetMinor: confirmed.budget);
      messenger.showSnackBar(SnackBar(content: Text(l.ads_activate_done)));
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(adsError(l, error))));
    }
    ref.invalidate(adsCampaignsProvider);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return AsyncView(
      value: ref.watch(adsCampaignsProvider),
      onRetry: () => ref.invalidate(adsCampaignsProvider),
      builder: (rows) => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(l.ads_create_description, style: theme.textTheme.bodySmall),
          if (!access.liveVerified) Text(l.ads_liveNotice, style: theme.textTheme.bodySmall),
          if (!access.activationEnabled) Notice(text: l.ads_activate_disabled),
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: TextButton.icon(
              icon: const Icon(Icons.add),
              key: const Key('ads-create'),
              label: Text(l.ads_tabs_create),
              onPressed: () => context.go('/ads/new'),
            ),
          ),
          if (rows.isEmpty) Text(l.ads_list_empty, style: theme.textTheme.bodySmall),
          for (final c in rows)
            Card(
              key: Key('ads-campaign-${c.id}'),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Expanded(child: Text(c.name, style: theme.textTheme.titleSmall)),
                    StatusChip(label: adsStatusLabel(l, c.status), positive: c.status == 'active', negative: c.status == 'failed'),
                  ]),
                  Text(
                    '${l.ads_create_budget(c.currency)}: ${moneyMinor(c.budgetMinor, c.currency)} · '
                    '${l.ads_list_spendToday(money(c.spendToday, c.currency))} · ${l.ads_list_spendTotal(money(c.spendToDate, c.currency))}',
                    style: theme.textTheme.bodySmall,
                  ),
                  if (c.pauseReason != null) Text(l.ads_list_reason(c.pauseReason!), style: theme.textTheme.bodySmall),
                  Wrap(spacing: 4, children: [
                    if (c.canPause)
                      TextButton(
                        key: Key('ads-pause-${c.id}'),
                        onPressed: () async {
                          final messenger = ScaffoldMessenger.of(context);
                          try {
                            await ref.read(adsRepositoryProvider).pause(c.id);
                          } on Object catch (error) {
                            messenger.showSnackBar(SnackBar(content: Text(adsError(l, error))));
                          }
                          ref.invalidate(adsCampaignsProvider);
                        },
                        child: Text(l.ads_list_pause),
                      ),
                    if (c.canRetry)
                      TextButton(
                        key: Key('ads-retry-${c.id}'),
                        onPressed: () async {
                          final messenger = ScaffoldMessenger.of(context);
                          try {
                            await ref.read(adsRepositoryProvider).provision(c.id);
                          } on Object catch (error) {
                            messenger.showSnackBar(SnackBar(content: Text(adsError(l, error))));
                          }
                          ref.invalidate(adsCampaignsProvider);
                        },
                        child: Text(l.ads_list_retry),
                      ),
                    if (c.canActivate && access.activationEnabled)
                      TextButton(
                        key: Key('ads-activate-${c.id}'),
                        onPressed: () => _activate(context, ref, c),
                        child: Text(l.ads_list_activate),
                      ),
                  ]),
                ]),
              ),
            ),
        ],
      ),
    );
  }
}

/// Activation spends real money: the exact phrase and the same budget again.
class _ActivateDialog extends StatefulWidget {
  const _ActivateDialog({required this.campaign, required this.phrase});
  final AdsCampaign campaign;
  final String phrase;

  @override
  State<_ActivateDialog> createState() => _ActivateDialogState();
}

class _ActivateDialogState extends State<_ActivateDialog> {
  final _phrase = TextEditingController();
  final _budget = TextEditingController();

  @override
  void dispose() {
    _phrase.dispose();
    _budget.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final c = widget.campaign;
    final ok = _phrase.text.trim() == widget.phrase && toMinor(_budget.text, c.currency) > 0;
    return AlertDialog(
      title: Text(l.ads_activate_title(c.name)),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(l.ads_activate_body(moneyMinor(c.budgetMinor, c.currency))),
          const SizedBox(height: 8),
          Text(l.ads_activate_phrase(widget.phrase), style: Theme.of(context).textTheme.bodySmall),
          TextField(
            key: const Key('activate-phrase'),
            controller: _phrase,
            autocorrect: false,
            enableSuggestions: false,
            textDirection: TextDirection.ltr,
            onChanged: (_) => setState(() {}),
          ),
          TextField(
            key: const Key('activate-budget'),
            controller: _budget,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(labelText: l.ads_activate_budget(c.currency)),
            onChanged: (_) => setState(() {}),
          ),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: Text(l.ads_activate_cancel)),
        FilledButton(
          key: const Key('activate-confirm'),
          onPressed: ok ? () => Navigator.pop(context, (phrase: _phrase.text.trim(), budget: toMinor(_budget.text, c.currency))) : null,
          child: Text(l.ads_activate_confirm),
        ),
      ],
    );
  }
}

/// Target CPA (used by the AI advice and alerts) and unlinking, as on the website.
class _LinkControls extends ConsumerStatefulWidget {
  const _LinkControls({required this.link});

  final AdAccountLink link;

  @override
  ConsumerState<_LinkControls> createState() => _LinkControlsState();
}

class _LinkControlsState extends ConsumerState<_LinkControls> {
  late final _target = TextEditingController(
    text: widget.link.cpaTargetMinor == null
        ? ''
        : (widget.link.cpaTargetMinor! / currencyOffset(widget.link.currency)).toString(),
  );
  bool _busy = false;

  @override
  void dispose() {
    _target.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      await action();
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(adsError(l, error))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    ref.invalidate(adsLinksProvider);
  }

  Future<void> _unlink() async {
    final l = AppLocalizations.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l.ads_accounts_unlink),
        content: Text('${widget.link.name} · ${widget.link.adAccountId}'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(l.ads_activate_cancel)),
          TextButton(
            key: const Key('unlink-confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: Text(l.ads_accounts_unlink),
          ),
        ],
      ),
    );
    if (ok == true) await _run(() => ref.read(adsRepositoryProvider).unlink(widget.link.id));
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final link = widget.link;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: TextField(
              key: Key('ads-cpa-${link.id}'),
              controller: _target,
              enabled: !_busy,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))],
              decoration: InputDecoration(labelText: l.ads_accounts_cpaTarget(link.currency), isDense: true),
            ),
          ),
          TextButton(
            key: Key('ads-cpa-save-${link.id}'),
            onPressed: _busy
                ? null
                : () => _run(() {
                      final text = _target.text.trim();
                      final minor = text.isEmpty ? null : toMinor(text, link.currency);
                      return ref.read(adsRepositoryProvider).setCpaTarget(link.id, minor == 0 ? null : minor);
                    }),
            child: Text(l.ads_accounts_saveTarget),
          ),
          IconButton(
            key: Key('ads-unlink-${link.id}'),
            tooltip: l.ads_accounts_unlink,
            icon: const Icon(Icons.link_off),
            onPressed: _busy ? null : _unlink,
          ),
        ],
      ),
    );
  }
}
