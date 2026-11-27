import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart' show DateFormat;
import 'package:url_launcher/url_launcher.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_client.dart';
import '../../core/providers.dart';
import '../../core/security/device_security.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../ads/ads_repository.dart' show moneyMinor;
import '../auth/password_recovery_pages.dart';
import '../workspace/workspace_models.dart' show newRequestId;

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;
DateTime? _d(Object? v) => v is String ? DateTime.tryParse(v) : null;
Map<String, Object?> _map(Object? v) => v is Map ? v.cast<String, Object?>() : const {};
List<Map<String, Object?>> _rows(Object? v) =>
    v is List ? [for (final r in v) if (r is Map) r.cast<String, Object?>()] : const [];

@immutable
class BillingSubscription {
  const BillingSubscription({
    required this.source,
    required this.providerLabel,
    required this.managementUrl,
    required this.status,
    required this.cancelAtPeriodEnd,
    required this.periodEnd,
  });
  final String source;
  final String providerLabel;
  final String? managementUrl;
  final String status;
  final bool cancelAtPeriodEnd;
  final DateTime? periodEnd;

  bool get fromStore => source == 'mobile_store';

  factory BillingSubscription.fromJson(Map<String, Object?> j) => BillingSubscription(
        source: _s(j['source'], 'web'),
        providerLabel: _s(j['provider_label'], _s(j['provider'])),
        managementUrl: j['management_url'] as String?,
        status: _s(j['status']),
        cancelAtPeriodEnd: j['cancel_at_period_end'] == true,
        periodEnd: _d(j['current_period_end']),
      );
}

@immutable
class BillingInvoice {
  const BillingInvoice({required this.number, required this.status, required this.currency, required this.totalMinor, required this.createdAt});
  final String number;
  final String status;
  final String currency;
  final int totalMinor;
  final DateTime? createdAt;
}

@immutable
class PaymentMethod {
  const PaymentMethod({required this.id, required this.brand, required this.last4, required this.expiry, required this.isDefault});
  final String id;
  final String brand;
  final String? last4;
  final String? expiry;
  final bool isDefault;
}

@immutable
class BillingSummary {
  const BillingSummary({
    required this.accountStatus,
    required this.planName,
    required this.seats,
    required this.limits,
    required this.usage,
    required this.subscription,
    required this.invoices,
    required this.walletMinor,
    required this.walletCurrency,
    this.planCode = '',
  });
  final String accountStatus;
  final String planName;

  /// Catalog code (free, professional, ...) to mark the current plan on the plans page.
  final String planCode;
  final int seats;
  final Map<String, Object?> limits;
  final Map<String, int> usage;
  final BillingSubscription? subscription;
  final List<BillingInvoice> invoices;
  final int walletMinor;
  final String walletCurrency;

  factory BillingSummary.fromJson(Map<String, Object?> j) {
    final account = _map(j['account']);
    final wallet = _map(j['wallet']);
    return BillingSummary(
      accountStatus: _s(account['status']),
      planName: _s(account['plan_name'], _s(account['plan'], 'free')),
      seats: _i(account['licensed_seats']),
      limits: _map(account['limits']),
      usage: {for (final e in _map(account['usage']).entries) e.key: _i(e.value)},
      subscription: j['subscription'] is Map ? BillingSubscription.fromJson(_map(j['subscription'])) : null,
      invoices: [
        for (final r in _rows(j['invoices']))
          BillingInvoice(
            number: _s(r['number'], _s(r['id'])),
            status: _s(r['status']),
            currency: _s(r['currency'], 'USD'),
            totalMinor: _i(r['total_minor']),
            createdAt: _d(r['created_at']),
          ),
      ],
      walletMinor: _i(wallet['balance_minor']),
      walletCurrency: _s(wallet['currency'], 'USD'),
      planCode: _s(account['plan'], 'free'),
    );
  }
}

/// Billing for the signed-in organization (vip-frontend's /billing page, without checkout).
class BillingRepository {
  BillingRepository(this._api);
  final ApiClient _api;

  Future<BillingSummary> summary() async => BillingSummary.fromJson(await _api.getJson('/billing'));

  Future<List<PaymentMethod>> methods() async => [
        for (final r in _rows(await _api.getList('/billing/payment-methods')))
          PaymentMethod(
            id: _s(r['id']),
            brand: _s(r['brand'], _s(r['type'])),
            last4: r['last4'] as String?,
            expiry: r['expiry_month'] is num ? '${r['expiry_month']}/${r['expiry_year']}' : null,
            isDefault: r['is_default'] == true,
          ),
      ];

  Future<void> cancelAtPeriodEnd() async =>
      _api.postJson('/billing/subscription/cancel', body: {'immediately': false}, retry: false);

  Future<void> resume() async => _api.postJson('/billing/subscription/resume', retry: false, headers: {'Idempotency-Key': newRequestId()});

  Future<void> makeDefault(String id) async =>
      _api.postJson('/billing/payment-methods/${Uri.encodeComponent(id)}/default', retry: false);

  Future<void> remove(String id) async => _api.deleteJson('/billing/payment-methods/${Uri.encodeComponent(id)}');

  Future<Uri?> portal(String locale) async {
    final url = (await _api.postJson('/billing/portal-session', body: {'locale': locale}, retry: false))['url'];
    final parsed = url is String ? Uri.tryParse(url) : null;
    return parsed != null && parsed.scheme == 'https' ? parsed : null;
  }
}

final billingRepositoryProvider = Provider<BillingRepository>((ref) => BillingRepository(ref.watch(apiClientProvider)));
final billingSummaryProvider = FutureProvider.autoDispose<BillingSummary>((ref) => ref.watch(billingRepositoryProvider).summary());
final paymentMethodsProvider = FutureProvider.autoDispose<List<PaymentMethod>>((ref) => ref.watch(billingRepositoryProvider).methods());

/// Plan, usage, subscription, invoices and saved cards. Buying a plan is not
/// offered in the store apps (that goes through the stores' own purchase flow).
class BillingPage extends ConsumerWidget {
  const BillingPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag());
    // Changing how you pay is refused on a rooted / jailbroken device.
    final compromised = ref.watch(deviceIntegrityProvider).value?.compromised ?? false;
    final repo = ref.read(billingRepositoryProvider);

    Future<void> act(Future<void> Function() action, String done, String failed) async {
      final messenger = ScaffoldMessenger.of(context);
      try {
        await action();
        messenger.showSnackBar(SnackBar(content: Text(done)));
      } on Object catch (error) {
        messenger.showSnackBar(SnackBar(content: Text(describeAccountError(l, error, failed))));
      }
      ref.invalidate(billingSummaryProvider);
      ref.invalidate(paymentMethodsProvider);
    }

    Future<bool> confirm(String text, String action) async =>
        await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            content: Text(text),
            actions: [
              TextButton(onPressed: () => Navigator.pop(context, false), child: Text(l.projects_cancel)),
              FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(action)),
            ],
          ),
        ) ==
        true;

    // Apple does not allow links to outside payment pages in the iOS app.
    final showPortal = defaultTargetPlatform != TargetPlatform.iOS || kIsWeb;

    return Scaffold(
      appBar: AppBar(
        title: Text(l.billing_eyebrow),
        actions: [
          IconButton(
            tooltip: l.billing_refresh,
            icon: const Icon(Icons.refresh),
            onPressed: () {
              ref.invalidate(billingSummaryProvider);
              ref.invalidate(paymentMethodsProvider);
            },
          ),
        ],
      ),
      body: AsyncView(
        value: ref.watch(billingSummaryProvider),
        onRetry: () => ref.invalidate(billingSummaryProvider),
        builder: (b) {
          final sub = b.subscription;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (compromised) ...[
                Notice(key: const Key('billing-compromised'), text: l.app_deviceCompromised, tone: NoticeTone.error),
                const SizedBox(height: 8),
              ],
              if (b.accountStatus == 'past_due') ...[
                Notice(text: l.billing_pastDueNotice, tone: NoticeTone.error),
                const SizedBox(height: 8),
              ],
              Card(
                child: ListTile(
                  title: Text(l.billing_currentPlan, style: theme.textTheme.labelMedium),
                  subtitle: Text(b.planName, key: const Key('billing-plan'), style: theme.textTheme.titleLarge),
                  trailing: Text('${l.billing_accountStatus}: ${b.accountStatus}', style: theme.textTheme.bodySmall),
                ),
              ),
              Align(
                alignment: AlignmentDirectional.centerStart,
                child: TextButton.icon(
                  key: const Key('billing-plans'),
                  icon: const Icon(Icons.workspace_premium_outlined),
                  label: Text(l.billing_plans),
                  onPressed: () => context.go('/billing/plans'),
                ),
              ),
              const SizedBox(height: 8),
              Text(l.billing_subscription, style: theme.textTheme.titleMedium),
              if (sub == null)
                Text(l.billing_noSubscription, style: theme.textTheme.bodySmall)
              else
                Card(
                  key: const Key('billing-subscription'),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${sub.fromStore ? l.billing_sourceMobileStore : l.billing_sourceWeb} · ${sub.providerLabel} · ${sub.status}'),
                      if (sub.periodEnd != null) Text(l.billing_renews(format.format(sub.periodEnd!.toLocal())), style: theme.textTheme.bodySmall),
                      if (sub.cancelAtPeriodEnd) Text(l.billing_cancellationScheduled, style: TextStyle(color: theme.colorScheme.error)),
                      Wrap(spacing: 4, children: [
                        if (sub.fromStore && sub.managementUrl != null)
                          TextButton(
                            onPressed: () {
                              final url = Uri.tryParse(sub.managementUrl!);
                              if (url != null && url.scheme == 'https') launchUrl(url, mode: LaunchMode.externalApplication);
                            },
                            child: Text(l.billing_manageStoreSubscription),
                          ),
                        if (!sub.fromStore && !sub.cancelAtPeriodEnd)
                          TextButton(
                            key: const Key('billing-cancel'),
                            onPressed: compromised
                                ? null
                                : () async {
                                    if (await confirm(l.billing_cancelConfirm, l.billing_cancelAtPeriodEnd)) {
                                      await act(repo.cancelAtPeriodEnd, l.billing_cancelScheduled, l.billing_cancelError);
                                    }
                                  },
                            child: Text(l.billing_cancelAtPeriodEnd),
                          ),
                        if (!sub.fromStore && sub.cancelAtPeriodEnd)
                          TextButton(
                            key: const Key('billing-resume'),
                            onPressed: compromised ? null : () => act(repo.resume, l.billing_resumeSuccess, l.billing_resumeError),
                            child: Text(l.billing_resumeSubscription),
                          ),
                        if (!sub.fromStore && showPortal)
                          TextButton(
                            key: const Key('billing-portal'),
                            onPressed: compromised
                                ? null
                                : () async {
                                    final messenger = ScaffoldMessenger.of(context);
                                    try {
                                      final url = await repo.portal(Localizations.localeOf(context).languageCode);
                                      if (url == null) throw StateError('unsafe portal url');
                                      await launchUrl(url, mode: LaunchMode.externalApplication);
                                    } on Object {
                                      messenger.showSnackBar(SnackBar(content: Text(l.billing_portalError)));
                                    }
                                  },
                            child: Text(l.billing_manageWithProvider),
                          ),
                      ]),
                    ]),
                  ),
                ),
              const SizedBox(height: 12),
              Text(l.billing_limitsAndUsage, style: theme.textTheme.titleMedium),
              if (b.limits.isEmpty) Text(l.billing_noLimits, style: theme.textTheme.bodySmall),
              for (final e in b.limits.entries)
                if (e.value is num)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(e.key.replaceAll('_', ' ')),
                    trailing: Text(b.usage.containsKey(e.key) ? '${b.usage[e.key]} / ${e.value}' : '${e.value}'),
                  ),
              Text('${l.billing_walletBalance}: ${moneyMinor(b.walletMinor, b.walletCurrency)} · ${l.billing_licensedSeats}: ${b.seats}',
                  style: theme.textTheme.bodySmall),
              const SizedBox(height: 12),
              Text(l.billing_paymentMethods, style: theme.textTheme.titleMedium),
              AsyncView(
                value: ref.watch(paymentMethodsProvider),
                onRetry: () => ref.invalidate(paymentMethodsProvider),
                builder: (methods) => methods.isEmpty
                    ? Text(l.billing_noPaymentMethods, style: theme.textTheme.bodySmall)
                    : Column(children: [
                        for (final m in methods)
                          ListTile(
                            key: Key('method-${m.id}'),
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.credit_card),
                            title: Text('${m.brand} •••• ${m.last4 ?? ''}'),
                            subtitle: Text([?m.expiry, if (m.isDefault) l.billing_defaultMethod].join(' · ')),
                            trailing: Wrap(children: [
                              if (!m.isDefault)
                                TextButton(
                                  onPressed: compromised ? null : () => act(() => repo.makeDefault(m.id), l.billing_paymentMethodUpdated, l.billing_methodError),
                                  child: Text(l.billing_makeDefault),
                                ),
                              IconButton(
                                tooltip: l.billing_remove,
                                icon: const Icon(Icons.delete_outline),
                                onPressed: compromised
                                    ? null
                                    : () async {
                                        if (await confirm(l.billing_removeMethodConfirm, l.billing_remove)) {
                                          await act(() => repo.remove(m.id), l.billing_paymentMethodRemoved, l.billing_methodError);
                                        }
                                      },
                              ),
                            ]),
                          ),
                      ]),
              ),
              const SizedBox(height: 12),
              Text(l.billing_invoices, style: theme.textTheme.titleMedium),
              if (b.invoices.isEmpty) Text(l.billing_noInvoices, style: theme.textTheme.bodySmall),
              for (final inv in b.invoices)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text('${l.billing_invoiceNumber} ${inv.number}'),
                  subtitle: Text([if (inv.createdAt != null) format.format(inv.createdAt!.toLocal()), inv.status].join(' · ')),
                  trailing: Text(moneyMinor(inv.totalMinor, inv.currency)),
                ),
            ],
          );
        },
      ),
    );
  }
}
