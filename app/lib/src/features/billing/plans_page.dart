import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/providers.dart';
import '../../core/security/device_security.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import 'billing_page.dart';
import 'store_purchases.dart';

/// A plan from the public catalog (the same one the website's pricing page used).
@immutable
class CatalogPlan {
  const CatalogPlan({
    required this.code,
    required this.name,
    required this.description,
    required this.features,
    required this.featured,
    required this.order,
  });

  final String code;
  final Map<String, String> name;
  final Map<String, String> description;
  final List<Map<String, String>> features;
  final bool featured;
  final int order;

  static Map<String, String> _text(Object? v) =>
      v is Map ? {for (final e in v.entries) if (e.value is String) '${e.key}': e.value as String} : const {};

  static String pick(Map<String, String> text, String language) => text[language] ?? text['en'] ?? text.values.firstOrNull ?? '';

  factory CatalogPlan.fromJson(Map<String, Object?> j) => CatalogPlan(
        code: (j['code'] as String?) ?? '',
        name: _text(j['name']),
        description: _text(j['description']),
        features: [for (final f in (j['features'] is List ? j['features']! as List : const [])) _text(f)],
        featured: j['featured'] == true,
        order: (j['order'] as num?)?.toInt() ?? 0,
      );
}

final catalogPlansProvider = FutureProvider.autoDispose<List<CatalogPlan>>((ref) async {
  final json = await ref.watch(apiClientProvider).getJson('/billing/catalog/public', auth: false);
  final plans = [
    for (final p in (json['plans'] is List ? json['plans']! as List : const []))
      if (p is Map && p['enabled'] != false) CatalogPlan.fromJson(p.cast<String, Object?>()),
  ]..sort((a, b) => a.order.compareTo(b.order));
  return plans;
});

/// Plans and subscribing through the App Store / Google Play.
class PlansPage extends ConsumerWidget {
  const PlansPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final language = Localizations.localeOf(context).languageCode;
    final current = ref.watch(billingSummaryProvider).value?.planCode;
    final catalog = ref.watch(storeCatalogProvider);
    final purchase = ref.watch(storePurchaseProvider);
    final compromised = ref.watch(deviceIntegrityProvider).value?.compromised ?? false;
    final busy = purchase.stage == PurchaseStage.pending || purchase.stage == PurchaseStage.verifying;
    final store = catalog.value;
    final canBuy = store != null && store.ready && !compromised && !busy;

    ref.listen(storePurchaseProvider, (previous, next) {
      final text = switch (next.stage) {
        PurchaseStage.done => l.app_purchaseActive,
        PurchaseStage.failed => l.app_purchaseFailed,
        _ => null,
      };
      if (text != null && previous?.stage != next.stage) {
        ScaffoldMessenger.of(context)
          ..clearSnackBars()
          ..showSnackBar(SnackBar(content: Text(text)));
      }
    });

    return Scaffold(
      appBar: AppBar(title: Text(l.billing_plans)),
      body: AsyncView(
        value: ref.watch(catalogPlansProvider),
        onRetry: () => ref.invalidate(catalogPlansProvider),
        builder: (plans) => ListView(
          key: const Key('plans-list'),
          padding: const EdgeInsets.all(16),
          children: [
            Text(l.billing_plansCopy, style: theme.textTheme.bodySmall),
            const SizedBox(height: 12),
            if (compromised) ...[
              Notice(key: const Key('plans-compromised'), text: l.app_deviceCompromised, tone: NoticeTone.error),
              const SizedBox(height: 12),
            ],
            if (catalog.hasValue && !(store?.ready ?? false)) ...[
              Notice(
                key: const Key('plans-store-unavailable'),
                text: kIsWeb || store?.store == null ? l.app_purchaseInStoreApp : l.app_purchaseNotReady,
              ),
              const SizedBox(height: 12),
            ],
            if (busy) ...[
              Row(children: [
                const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                const SizedBox(width: 12),
                Expanded(child: Text(l.app_purchasePending, key: const Key('plans-pending'))),
              ]),
              const SizedBox(height: 12),
            ],
            for (final plan in plans)
              Card(
                key: Key('plan-${plan.code}'),
                shape: plan.featured
                    ? RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                        side: BorderSide(color: theme.colorScheme.primary),
                      )
                    : null,
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(children: [
                        Expanded(
                          child: Text(CatalogPlan.pick(plan.name, language), style: theme.textTheme.titleMedium),
                        ),
                        if (plan.code == current)
                          Chip(key: Key('plan-current-${plan.code}'), label: Text(l.billing_currentPlan)),
                      ]),
                      if (plan.description.isNotEmpty)
                        Text(CatalogPlan.pick(plan.description, language), style: theme.textTheme.bodySmall),
                      const SizedBox(height: 8),
                      for (final f in plan.features)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 2),
                          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            const Icon(Icons.check, size: 16),
                            const SizedBox(width: 8),
                            Expanded(child: Text(CatalogPlan.pick(f, language))),
                          ]),
                        ),
                      if (plan.code != current)
                        for (final offer in store?.offersFor(plan.code) ?? const <StoreOffer>[]) ...[
                          const SizedBox(height: 8),
                          FilledButton(
                            key: Key('buy-${offer.mapping.id}'),
                            onPressed: canBuy ? () => ref.read(storePurchaseProvider.notifier).buy(offer) : null,
                            child: Text('${l.billing_selectPlan} · ${offer.price}'),
                          ),
                        ],
                    ],
                  ),
                ),
              ),
            if (store?.ready ?? false) ...[
              const SizedBox(height: 8),
              TextButton.icon(
                key: const Key('plans-restore'),
                onPressed: compromised || busy ? null : () => ref.read(storePurchaseProvider.notifier).restore(),
                icon: const Icon(Icons.restore),
                label: Text(l.billing_restorePurchases),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
