import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart' show NumberFormat;

import '../../core/api/api_client.dart';
import '../../core/providers.dart';

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;
double? _n(Object? v) => v is num ? v.toDouble() : null;
DateTime? _d(Object? v) => v is String ? DateTime.tryParse(v) : null;
List<Map<String, Object?>> _rows(Object? v) =>
    v is List ? [for (final r in v) if (r is Map) r.cast<String, Object?>()] : const [];
Map<String, Object?> _map(Object? v) => v is Map ? v.cast<String, Object?>() : const {};

// Meta "offset 1" currencies: budgets are already whole units (same list as the website).
const _zeroDecimal = {'CLP', 'COP', 'CRC', 'HUF', 'ISK', 'IDR', 'JPY', 'KRW', 'PYG', 'TWD', 'VND'};
int currencyOffset(String currency) => _zeroDecimal.contains(currency.toUpperCase()) ? 1 : 100;

int toMinor(String value, String currency) {
  final parsed = double.tryParse(value.trim());
  if (parsed == null || !parsed.isFinite || parsed <= 0) return 0;
  return (parsed * currencyOffset(currency)).round();
}

String money(num? amount, String currency) {
  if (amount == null) return '—';
  try {
    return NumberFormat.simpleCurrency(name: currency).format(amount);
  } on Object {
    return '$currency ${amount.toStringAsFixed(2)}';
  }
}

String moneyMinor(int? minor, String currency) => minor == null ? '—' : money(minor / currencyOffset(currency), currency);

@immutable
class AdsAccess {
  const AdsAccess({
    required this.allowed,
    required this.activationEnabled,
    required this.activationPhrase,
    required this.dailyCapMinor,
    required this.lifetimeCapMinor,
    required this.liveVerified,
  });
  final bool allowed;
  final bool activationEnabled;
  final String activationPhrase;
  final int dailyCapMinor;
  final int lifetimeCapMinor;
  final bool liveVerified;

  factory AdsAccess.fromJson(Map<String, Object?> j) => AdsAccess(
        allowed: j['allowed'] == true,
        activationEnabled: j['activation_enabled'] == true,
        activationPhrase: _s(j['activation_phrase']),
        dailyCapMinor: _i(j['daily_cap_minor']),
        lifetimeCapMinor: _i(j['lifetime_cap_minor']),
        liveVerified: j['live_verified'] == true,
      );
}

@immutable
class AdAccountLink {
  const AdAccountLink({
    required this.id,
    required this.name,
    required this.adAccountId,
    required this.currency,
    required this.syncState,
    required this.syncError,
    required this.lastSyncAt,
    required this.syncedThrough,
    this.cpaTargetMinor,
  });
  final String id;
  final String name;
  final String adAccountId;
  final int? cpaTargetMinor;
  final String currency;
  final String syncState;
  final String? syncError;
  final DateTime? lastSyncAt;
  final String? syncedThrough;

  factory AdAccountLink.fromJson(Map<String, Object?> j) => AdAccountLink(
        id: _s(j['id']),
        name: _s(j['name']),
        adAccountId: _s(j['ad_account_id']),
        currency: _s(j['currency'], 'USD'),
        syncState: _s(j['sync_state']),
        syncError: j['sync_error'] as String?,
        lastSyncAt: _d(j['last_sync_at']),
        syncedThrough: j['insights_synced_through'] as String?,
        cpaTargetMinor: j['cpa_target_minor'] is num ? _i(j['cpa_target_minor']) : null,
      );
}

@immutable
class AdsKpi {
  const AdsKpi({required this.value, required this.changePct});
  final double? value;
  final double? changePct;
}

@immutable
class AdsCampaignRow {
  const AdsCampaignRow({required this.name, required this.spend, required this.ctr, required this.cpa, required this.roas});
  final String name;
  final double? spend;
  final double? ctr;
  final double? cpa;
  final double? roas;
}

@immutable
class AdsDashboard {
  const AdsDashboard({
    required this.currency,
    required this.hasData,
    required this.from,
    required this.to,
    required this.kpis,
    required this.top,
    required this.alerts,
    required this.syncedThrough,
  });
  final String currency;
  final bool hasData;
  final String from;
  final String to;
  final Map<String, AdsKpi> kpis;
  final List<AdsCampaignRow> top;
  final List<String> alerts;
  final String? syncedThrough;

  factory AdsDashboard.fromJson(Map<String, Object?> j) {
    final period = _map(j['period']);
    final campaigns = _map(j['campaigns']);
    return AdsDashboard(
      currency: _s(j['currency'], 'USD'),
      hasData: j['has_data'] == true,
      from: _s(period['from']),
      to: _s(period['to']),
      kpis: {
        for (final e in _map(j['kpis']).entries)
          e.key: AdsKpi(value: _n(_map(e.value)['value']), changePct: _n(_map(e.value)['change_pct'])),
      },
      top: [
        for (final c in _rows(campaigns['top']))
          AdsCampaignRow(name: _s(c['name']), spend: _n(c['spend']), ctr: _n(c['ctr']), cpa: _n(c['cpa']), roas: _n(c['roas'])),
      ],
      alerts: [for (final a in _rows(j['alerts'])) _s(a['type'])],
      syncedThrough: j['synced_through'] as String?,
    );
  }
}

@immutable
class AdsRecommendation {
  const AdsRecommendation({required this.type, required this.title, required this.action, required this.rationale, required this.evidence});
  final String type;
  final String title;
  final String action;
  final String rationale;
  final Map<String, num> evidence;
}

@immutable
class AdsRecommendationRun {
  const AdsRecommendationRun({required this.items, required this.model, required this.rejected});
  final List<AdsRecommendation> items;
  final String model;
  final int rejected;

  factory AdsRecommendationRun.fromJson(Map<String, Object?> j) => AdsRecommendationRun(
        model: _s(j['model']),
        rejected: _i(j['rejected']),
        items: [
          for (final r in _rows(j['items']))
            AdsRecommendation(
              type: _s(r['type']),
              title: _s(r['title']),
              action: _s(r['action']),
              rationale: _s(r['rationale']),
              evidence: {for (final e in _map(r['evidence']).entries) if (e.value is num) e.key: e.value! as num},
            ),
        ],
      );
}

@immutable
class AdsCampaign {
  const AdsCampaign({
    required this.id,
    required this.name,
    required this.objective,
    required this.status,
    required this.currency,
    required this.dailyBudgetMinor,
    required this.lifetimeBudgetMinor,
    required this.spendToday,
    required this.spendToDate,
    required this.pauseReason,
    required this.errorCode,
  });
  final String id;
  final String name;
  final String objective;
  final String status;
  final String currency;
  final int? dailyBudgetMinor;
  final int? lifetimeBudgetMinor;
  final double spendToday;
  final double spendToDate;
  final String? pauseReason;
  final String? errorCode;

  /// The budget the activation confirmation must repeat.
  int? get budgetMinor => dailyBudgetMinor ?? lifetimeBudgetMinor;
  bool get canPause => status == 'active';
  bool get canActivate => status == 'paused' || status == 'auto_paused';
  bool get canRetry => status == 'failed' || status == 'draft';

  factory AdsCampaign.fromJson(Map<String, Object?> j) => AdsCampaign(
        id: _s(j['id']),
        name: _s(j['name']),
        objective: _s(j['objective']),
        status: _s(j['status']),
        currency: _s(j['currency'], 'USD'),
        dailyBudgetMinor: j['daily_budget_minor'] is num ? _i(j['daily_budget_minor']) : null,
        lifetimeBudgetMinor: j['lifetime_budget_minor'] is num ? _i(j['lifetime_budget_minor']) : null,
        spendToday: _n(j['spend_today']) ?? 0,
        spendToDate: _n(j['spend_to_date']) ?? 0,
        pauseReason: j['pause_reason'] as String?,
        errorCode: j['error_code'] as String?,
      );
}

/// Meta Ads management, the same endpoints as vip-frontend/src/lib/api.ts.
class AdsRepository {
  AdsRepository(this._api);
  final ApiClient _api;

  Future<AdsAccess> access() async => AdsAccess.fromJson(await _api.getJson('/ads/access'));

  Future<List<AdAccountLink>> links() async =>
      [for (final r in _rows((await _api.getJson('/ads/accounts'))['items'])) AdAccountLink.fromJson(r)];

  Future<void> sync(String linkId) async => _api.postJson('/ads/accounts/${Uri.encodeComponent(linkId)}/sync', retry: false);

  Future<AdsDashboard> dashboard(String linkId) async =>
      AdsDashboard.fromJson(await _api.getJson('/ads/analytics', query: {'link_id': linkId}));

  Future<AdsRecommendationRun?> latestRecommendations(String linkId) async {
    final item = (await _api.getJson('/ads/recommendations', query: {'link_id': linkId}))['item'];
    return item is Map ? AdsRecommendationRun.fromJson(item.cast<String, Object?>()) : null;
  }

  Future<AdsRecommendationRun> recommend(String linkId, {required String language, required bool externalAllowed}) async =>
      AdsRecommendationRun.fromJson(await _api.postJson('/ads/recommendations', body: {
        'link_id': linkId,
        'language': language,
        'external_processing_confirmed': externalAllowed,
      }, retry: false));

  Future<List<AdsCampaign>> campaigns() async =>
      [for (final r in _rows((await _api.getJson('/ads/campaigns'))['items'])) AdsCampaign.fromJson(r)];

  /// Creates the campaign on Meta, always PAUSED. The key makes a repeated tap harmless.
  Future<AdsCampaign> create(Map<String, Object?> input) async =>
      AdsCampaign.fromJson(await _api.postJson('/ads/campaigns', body: input, retry: false));

  Future<void> provision(String id) async =>
      _api.postJson('/ads/campaigns/${Uri.encodeComponent(id)}/provision', retry: false);

  Future<void> setCpaTarget(String linkId, int? minor) async =>
      _api.patchJson('/ads/accounts/${Uri.encodeComponent(linkId)}', body: {'cpa_target_minor': minor});

  Future<void> unlink(String linkId) async => _api.deleteJson('/ads/accounts/${Uri.encodeComponent(linkId)}');

  Future<void> pause(String id) async => _api.postJson('/ads/campaigns/${Uri.encodeComponent(id)}/pause', retry: false);

  /// Real spending starts here, so the server checks the typed phrase and the repeated budget.
  Future<void> activate(String id, {required String phrase, required int budgetMinor}) async => _api.postJson(
        '/ads/campaigns/${Uri.encodeComponent(id)}/activate',
        body: {'confirmation': phrase, 'confirmed_budget_minor': budgetMinor},
        retry: false,
      );
}

final adsRepositoryProvider = Provider<AdsRepository>((ref) => AdsRepository(ref.watch(apiClientProvider)));
final adsAccessProvider = FutureProvider.autoDispose<AdsAccess>((ref) => ref.watch(adsRepositoryProvider).access());
final adsLinksProvider = FutureProvider.autoDispose<List<AdAccountLink>>((ref) => ref.watch(adsRepositoryProvider).links());
final adsCampaignsProvider = FutureProvider.autoDispose<List<AdsCampaign>>((ref) => ref.watch(adsRepositoryProvider).campaigns());
final adsDashboardProvider =
    FutureProvider.autoDispose.family<AdsDashboard, String>((ref, id) => ref.watch(adsRepositoryProvider).dashboard(id));
final adsRecommendationsProvider =
    FutureProvider.autoDispose.family<AdsRecommendationRun?, String>((ref, id) => ref.watch(adsRepositoryProvider).latestRecommendations(id));

/// Owner-reviewed paid-campaign planning (GS-12): AIOS simulates and advises, nothing spends.
@immutable
class PaidAdAccount {
  const PaidAdAccount({
    required this.id,
    required this.provider,
    required this.displayName,
    required this.currency,
    required this.liveObjectives,
  });
  final String id;
  final String provider;
  final String displayName;
  final String currency;
  final List<String> liveObjectives;

  factory PaidAdAccount.fromJson(Map<String, Object?> j) => PaidAdAccount(
        id: _s(j['id']),
        provider: _s(j['provider']),
        displayName: _s(j['display_name']),
        currency: _s(j['currency'], 'USD'),
        liveObjectives: [for (final o in (j['live_objectives'] is List ? j['live_objectives']! as List : const [])) if (o is String) o],
      );
}

@immutable
class PaidReadiness {
  const PaidReadiness({required this.campaignsVisible, required this.accounts});
  final bool campaignsVisible;
  final List<PaidAdAccount> accounts;

  factory PaidReadiness.fromJson(Map<String, Object?> j) => PaidReadiness(
        campaignsVisible: j['campaigns_visible'] == true,
        accounts: [for (final r in _rows(j['linked_ad_accounts'])) PaidAdAccount.fromJson(r)],
      );
}

@immutable
class PaidCampaign {
  const PaidCampaign({
    required this.id,
    required this.name,
    required this.objective,
    required this.approved,
    required this.currency,
    required this.totalBudgetMinor,
    required this.dailyCapMinor,
    required this.deliveryStage,
    required this.manualReview,
  });
  final String id;
  final String name;
  final String objective;
  final bool approved;
  final String currency;
  final int totalBudgetMinor;
  final int dailyCapMinor;
  final String deliveryStage;
  final bool manualReview;

  factory PaidCampaign.fromJson(Map<String, Object?> j) => PaidCampaign(
        id: _s(j['id']),
        name: _s(j['name']),
        objective: _s(j['objective']),
        approved: j['approval_status'] == 'approved',
        currency: _s(j['currency'], 'USD'),
        totalBudgetMinor: _i(j['total_budget_minor']),
        dailyCapMinor: _i(j['daily_budget_cap_minor']),
        deliveryStage: _s(j['delivery_stage'], 'aios_analysis'),
        manualReview: j['manual_review_required'] == true,
      );
}

@immutable
class PaidAssessment {
  const PaidAssessment({required this.recommendation, required this.cpaMinor, required this.roas, required this.currency});
  final String recommendation;
  final int? cpaMinor;
  final double roas;
  final String currency;

  factory PaidAssessment.fromJson(Map<String, Object?> j) {
    final assessment = _map(j['budget_assessment']);
    return PaidAssessment(
      recommendation: _s(assessment['recommendation']),
      cpaMinor: assessment['observed_cpa_minor'] is num ? _i(assessment['observed_cpa_minor']) : null,
      roas: _n(assessment['observed_roas']) ?? 0,
      currency: _s(_map(j['campaign'])['currency'], 'USD'),
    );
  }
}

class PaidCampaignRepository {
  PaidCampaignRepository(this._api);
  final ApiClient _api;

  /// Null when planning is not available to this account (the page then shows ads only).
  Future<PaidReadiness?> readiness() async {
    try {
      return PaidReadiness.fromJson(await _api.getJson('/growth-social/paid-campaigns/readiness'));
    } on Object {
      return null;
    }
  }

  Future<List<PaidCampaign>> list() async =>
      [for (final r in _rows((await _api.getJson('/growth-social/paid-campaigns'))['items'])) PaidCampaign.fromJson(r)];

  Future<PaidAssessment> prepareAndSimulate(Map<String, Object?> input) async => PaidAssessment.fromJson(
        await _api.postJson('/growth-social/paid-campaigns/prepare-and-simulate', body: input, retry: false),
      );
}

final paidCampaignRepositoryProvider =
    Provider<PaidCampaignRepository>((ref) => PaidCampaignRepository(ref.watch(apiClientProvider)));
final paidReadinessProvider =
    FutureProvider.autoDispose<PaidReadiness?>((ref) => ref.watch(paidCampaignRepositoryProvider).readiness());
final paidCampaignsProvider =
    FutureProvider.autoDispose<List<PaidCampaign>>((ref) => ref.watch(paidCampaignRepositoryProvider).list());
