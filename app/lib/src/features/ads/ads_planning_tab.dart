import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart' show NumberFormat;

import '../../../l10n/generated/app_localizations.dart';
import '../../widgets/async_view.dart';
import '../../widgets/error_text.dart';
import '../../widgets/notice.dart';
import 'ads_repository.dart';

/// The website's planning form works in cents for every currency; kept the same here.
int _cents(String value) {
  final parsed = double.tryParse(value.trim());
  if (parsed == null || !parsed.isFinite || parsed <= 0) return 0;
  return (parsed * 100).round();
}

String _amount(int minor, String currency) {
  try {
    return NumberFormat.simpleCurrency(name: currency, decimalDigits: 2).format(minor / 100);
  } on Object {
    return '$currency ${(minor / 100).toStringAsFixed(2)}';
  }
}

const _stages = [
  'aios_analysis',
  'awaiting_owner',
  'owner_approved',
  'live_plan_ready',
  'provider_preparation',
  'paused_on_meta',
];

String _stageLabel(AppLocalizations l, String stage) => switch (stage) {
      'aios_analysis' => l.campaigns_stageAnalysis,
      'awaiting_owner' => l.campaigns_stageAwaitingOwner,
      'owner_approved' => l.campaigns_stageOwnerApproved,
      'live_plan_ready' => l.campaigns_stageLivePlan,
      'provider_preparation' => l.campaigns_stageProviderPreparing,
      'paused_on_meta' => l.campaigns_stagePausedMeta,
      'manual_review' => l.campaigns_stageManualReview,
      _ => stage,
    };

String _recommendation(AppLocalizations l, String value) => switch (value) {
      'increase_candidate' => l.campaigns_recommendIncrease,
      'decrease_or_rework' => l.campaigns_recommendDecrease,
      'keep_and_measure' => l.campaigns_recommendHold,
      _ => l.campaigns_recommendRework,
    };

/// AIOS budget advice: the person sets the budget, AIOS simulates (no spend), the owner approves.
class AdsPlanningTab extends ConsumerStatefulWidget {
  const AdsPlanningTab({super.key, required this.readiness});

  final PaidReadiness readiness;

  @override
  ConsumerState<AdsPlanningTab> createState() => _AdsPlanningTabState();
}

class _AdsPlanningTabState extends ConsumerState<AdsPlanningTab> {
  final _name = TextEditingController();
  final _total = TextEditingController();
  final _daily = TextEditingController();
  final _cpa = TextEditingController();
  final _roas = TextEditingController();
  final _countries = TextEditingController();
  final _placements = TextEditingController(text: 'feed');
  final _headline = TextEditingController();
  final _url = TextEditingController();
  final _body = TextEditingController();
  late String? _accountId = widget.readiness.accounts.firstOrNull?.id;
  String _objective = 'traffic';
  bool _busy = false;
  String? _error;
  PaidAssessment? _result;

  @override
  void dispose() {
    for (final c in [_name, _total, _daily, _cpa, _roas, _countries, _placements, _headline, _url, _body]) {
      c.dispose();
    }
    super.dispose();
  }

  PaidAdAccount? get _account =>
      widget.readiness.accounts.where((a) => a.id == _accountId).firstOrNull ?? widget.readiness.accounts.firstOrNull;

  Future<void> _submit() async {
    final l = AppLocalizations.of(context);
    final total = _cents(_total.text);
    final daily = _cents(_daily.text);
    final cpa = _cpa.text.trim().isEmpty ? 0 : _cents(_cpa.text);
    final roas = _roas.text.trim().isEmpty ? 0.0 : (double.tryParse(_roas.text.trim()) ?? -1);
    String? problem;
    if (_name.text.trim().isEmpty || total == 0 || daily == 0 || daily > total) {
      problem = l.campaigns_invalidBudget;
    } else if (_account == null) {
      problem = l.campaigns_accountRequired;
    } else if (_cpa.text.trim().isNotEmpty && cpa == 0) {
      problem = l.campaigns_invalidCpa;
    } else if (_roas.text.trim().isNotEmpty && !(roas > 0)) {
      problem = l.campaigns_invalidRoas;
    }
    final countries = [
      for (final c in _countries.text.split(','))
        if (c.trim().isNotEmpty) c.trim().toUpperCase(),
    ];
    if (problem == null && countries.isEmpty) problem = l.campaigns_countryRequired;
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    final placements = [
      for (final p in _placements.text.split(','))
        if (p.trim().isNotEmpty) p.trim().toLowerCase(),
    ];
    setState(() {
      _busy = true;
      _error = null;
      _result = null;
    });
    try {
      final result = await ref.read(paidCampaignRepositoryProvider).prepareAndSimulate({
        'campaign_name': _name.text.trim(),
        'objective': _objective,
        'social_account_id': _account!.id,
        'total_budget_minor': total,
        'daily_budget_cap_minor': daily,
        'max_cpa_minor': cpa == 0 ? null : cpa,
        'min_roas': roas > 0 ? roas : null,
        'target_countries': countries,
        'placements': placements.isEmpty ? ['feed'] : placements,
        'headline': _headline.text.trim(),
        'body': _body.text.trim(),
        'destination_url': _url.text.trim().isEmpty ? null : _url.text.trim(),
        'days': 3,
      });
      if (!mounted) return;
      setState(() => _result = result);
      ref.invalidate(paidCampaignsProvider);
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeError(l, error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final account = _account;
    const gap = SizedBox(height: 12);
    TextField field(String key, TextEditingController c, String label,
            {TextInputType? keyboard, int lines = 1, String? hint, bool ltr = false}) =>
        TextField(
          key: Key('plan-$key'),
          controller: c,
          enabled: !_busy,
          keyboardType: keyboard,
          minLines: lines,
          maxLines: lines == 1 ? 1 : lines + 2,
          textDirection: ltr ? TextDirection.ltr : null,
          inputFormatters: [LengthLimitingTextInputFormatter(lines == 1 ? 255 : 2000)],
          decoration: InputDecoration(labelText: label, hintText: hint),
        );
    const money = TextInputType.numberWithOptions(decimal: true);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(l.campaigns_createTitle, style: theme.textTheme.titleMedium),
        const SizedBox(height: 4),
        Text(l.campaigns_createDescription, style: theme.textTheme.bodySmall),
        gap,
        field('name', _name, l.campaigns_name, hint: l.campaigns_namePlaceholder),
        gap,
        DropdownButtonFormField<String>(
          key: const Key('plan-objective'),
          initialValue: _objective,
          isExpanded: true,
          decoration: InputDecoration(labelText: l.campaigns_objective),
          items: [
            for (final (value, label) in [
              ('sales', l.campaigns_objectiveSales),
              ('leads', l.campaigns_objectiveLeads),
              ('traffic', l.campaigns_objectiveTraffic),
              ('awareness', l.campaigns_objectiveAwareness),
            ])
              DropdownMenuItem(
                value: value,
                child: Text(
                  '$label — ${account?.liveObjectives.contains(value) == true ? l.campaigns_objectiveLiveReady : l.campaigns_objectiveAnalysisOnly}',
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          ],
          onChanged: _busy ? null : (v) => setState(() => _objective = v ?? 'traffic'),
        ),
        Text(l.campaigns_objectiveSupportNote, style: theme.textTheme.bodySmall),
        gap,
        if (widget.readiness.accounts.isEmpty)
          Notice(key: const Key('plan-no-accounts'), text: l.campaigns_accountRequired)
        else
          DropdownButtonFormField<String>(
            key: const Key('plan-account'),
            initialValue: account?.id,
            isExpanded: true,
            decoration: InputDecoration(labelText: l.campaigns_adAccount),
            items: [
              for (final a in widget.readiness.accounts)
                DropdownMenuItem(
                  value: a.id,
                  child: Text('${a.displayName} · ${a.provider} · ${a.currency}', overflow: TextOverflow.ellipsis),
                ),
            ],
            onChanged: _busy ? null : (v) => setState(() => _accountId = v),
          ),
        gap,
        Row(children: [
          Expanded(child: field('total', _total, l.campaigns_totalBudget, keyboard: money)),
          const SizedBox(width: 12),
          Expanded(child: field('daily', _daily, l.campaigns_dailyBudget, keyboard: money)),
        ]),
        gap,
        Row(children: [
          Expanded(child: field('cpa', _cpa, l.campaigns_maxCpa, keyboard: money)),
          const SizedBox(width: 12),
          Expanded(child: field('roas', _roas, l.campaigns_minRoas, keyboard: money)),
        ]),
        gap,
        field('countries', _countries, l.campaigns_countries, hint: 'AE,SA'),
        gap,
        field('placements', _placements, l.campaigns_placements, hint: 'feed,stories'),
        gap,
        field('headline', _headline, l.campaigns_headline),
        gap,
        field('url', _url, l.campaigns_destinationUrl, keyboard: TextInputType.url, hint: 'https://', ltr: true),
        gap,
        field('body', _body, l.campaigns_body, lines: 3),
        gap,
        Notice(text: l.campaigns_freedomNotice),
        if (_error != null) ...[
          gap,
          Text(_error!, key: const Key('plan-error'), style: TextStyle(color: theme.colorScheme.error)),
        ],
        gap,
        FilledButton.icon(
          key: const Key('plan-submit'),
          onPressed: _busy ? null : _submit,
          icon: const Icon(Icons.auto_awesome),
          label: Text(_busy ? l.campaigns_analyzing : l.campaigns_analyze),
        ),
        if (_result != null) ...[
          const SizedBox(height: 16),
          Card(
            key: const Key('plan-result'),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(l.campaigns_analysisTitle, style: theme.textTheme.titleMedium),
                  Text(l.campaigns_analysisDescription, style: theme.textTheme.bodySmall),
                  const SizedBox(height: 4),
                  Text(l.campaigns_simulationDisclaimer, style: theme.textTheme.bodySmall),
                  const Divider(height: 24),
                  Text('${l.campaigns_recommendation}: ${_recommendation(l, _result!.recommendation)}'),
                  Text(
                    '${l.campaigns_simulatedCpa}: '
                    '${_result!.cpaMinor == null ? '—' : _amount(_result!.cpaMinor!, _result!.currency)}',
                  ),
                  Text('${l.campaigns_simulatedRoas}: ${_result!.roas.toStringAsFixed(2)}'),
                  Text('${l.campaigns_status}: ${l.campaigns_awaitingOwner}'),
                  const SizedBox(height: 8),
                  Text(l.campaigns_analysisSafety, style: theme.textTheme.bodySmall),
                ],
              ),
            ),
          ),
        ],
        const SizedBox(height: 24),
        Text(l.campaigns_historyTitle, style: theme.textTheme.titleMedium),
        const SizedBox(height: 8),
        AsyncView(
          value: ref.watch(paidCampaignsProvider),
          onRetry: () => ref.invalidate(paidCampaignsProvider),
          builder: (rows) => rows.isEmpty
              ? Text(l.campaigns_empty, style: theme.textTheme.bodySmall)
              : Column(children: [for (final c in rows) _HistoryCard(campaign: c)]),
        ),
      ],
    );
  }
}

class _HistoryCard extends StatelessWidget {
  const _HistoryCard({required this.campaign});

  final PaidCampaign campaign;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final c = campaign;
    final progress = c.deliveryStage == 'manual_review' ? 4 : _stages.indexOf(c.deliveryStage).clamp(0, _stages.length);
    return Card(
      key: Key('plan-campaign-${c.id}'),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(child: Text(c.name, style: theme.textTheme.titleSmall)),
              Chip(label: Text(c.approved ? l.campaigns_approved : l.campaigns_awaitingOwner)),
            ]),
            Text(
              '${c.objective} · ${_amount(c.totalBudgetMinor, c.currency)} · '
              '${l.campaigns_dailyShort} ${_amount(c.dailyCapMinor, c.currency)}',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            Text(l.campaigns_deliveryTitle, style: theme.textTheme.labelMedium),
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final (index, stage) in _stages.indexed)
                  Chip(
                    visualDensity: VisualDensity.compact,
                    avatar: Icon(
                      index < progress
                          ? Icons.check_circle
                          : index == progress
                              ? Icons.radio_button_checked
                              : Icons.radio_button_unchecked,
                      size: 16,
                    ),
                    label: Text(_stageLabel(l, stage), style: theme.textTheme.labelSmall),
                  ),
              ],
            ),
            if (c.deliveryStage == 'paused_on_meta') ...[
              const SizedBox(height: 8),
              Notice(text: l.campaigns_pausedMetaNote),
            ],
            if (c.manualReview) ...[
              const SizedBox(height: 8),
              Notice(text: l.campaigns_manualReviewNote, tone: NoticeTone.error),
            ],
            const SizedBox(height: 4),
            Text(l.campaigns_noAutoSpend, style: theme.textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}
