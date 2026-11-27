import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart' show DateFormat;

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_exception.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import 'security_lab_repository.dart';

String securityError(AppLocalizations l, Object error, String fallback, {SecurityLabAccess? access}) {
  if (error is! ApiException) return fallback;
  return switch (error.code) {
    'SECURITY_CONCURRENT_SCAN_LIMIT_REACHED' => l.securityLab_errors_SECURITY_CONCURRENT_SCAN_LIMIT_REACHED,
    'SECURITY_DNS_TIMEOUT' => l.securityLab_errors_SECURITY_DNS_TIMEOUT,
    'SECURITY_DNS_VERIFICATION_FAILED' => l.securityLab_errors_SECURITY_DNS_VERIFICATION_FAILED,
    'SECURITY_MONTHLY_SCAN_LIMIT_REACHED' => l.securityLab_errors_SECURITY_MONTHLY_SCAN_LIMIT_REACHED('${access?.maxScansPerMonth ?? ''}'),
    'SECURITY_PLAN_REQUIRED' => l.securityLab_errors_SECURITY_PLAN_REQUIRED,
    'SECURITY_PROFILE_NOT_ALLOWED' => l.securityLab_errors_SECURITY_PROFILE_NOT_ALLOWED,
    'SECURITY_TARGET_LIMIT_REACHED' => l.securityLab_errors_SECURITY_TARGET_LIMIT_REACHED('${access?.maxTargets ?? ''}'),
    'SECURITY_TARGET_REVERIFICATION_FAILED' => l.securityLab_errors_SECURITY_TARGET_REVERIFICATION_FAILED,
    _ => error.message.isNotEmpty ? error.message : fallback,
  };
}

String severityLabel(AppLocalizations l, String s) => switch (s) {
      'critical' => l.securityLab_severities_critical,
      'high' => l.securityLab_severities_high,
      'medium' => l.securityLab_severities_medium,
      'low' => l.securityLab_severities_low,
      _ => l.securityLab_severities_info,
    };

String scanStatusLabel(AppLocalizations l, String s) => switch (s) {
      'queued' => l.securityLab_scanStatus_queued,
      'running' => l.securityLab_scanStatus_running,
      'completed' => l.securityLab_scanStatus_completed,
      'failed' => l.securityLab_scanStatus_failed,
      'cancelled' => l.securityLab_scanStatus_cancelled,
      _ => s,
    };

String profileLabel(AppLocalizations l, String s) => switch (s) {
      'passive' => l.securityLab_profiles_passive,
      'standard' => l.securityLab_profiles_standard,
      'advanced' => l.securityLab_profiles_advanced,
      'elite' => l.securityLab_profiles_elite,
      _ => s,
    };

const _severityOrder = ['critical', 'high', 'medium', 'low', 'info'];

/// Website security scanning of sites the user proved they own.
class SecurityLabPage extends ConsumerStatefulWidget {
  const SecurityLabPage({super.key, this.pollInterval = const Duration(seconds: 5)});
  final Duration pollInterval;

  @override
  ConsumerState<SecurityLabPage> createState() => _SecurityLabPageState();
}

class _SecurityLabPageState extends ConsumerState<SecurityLabPage> {
  final _origin = TextEditingController();
  String? _targetId;
  String? _profile;
  bool _busy = false;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(widget.pollInterval, (_) {
      final scans = ref.read(securityScansProvider).value;
      if (scans != null && scans.any((s) => s.isActive)) ref.invalidate(securityScansProvider);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _origin.dispose();
    super.dispose();
  }

  SecurityLabRepository get _repo => ref.read(securityLabRepositoryProvider);

  Future<void> _run(Future<void> Function() action, String failed, {String? done}) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final access = ref.read(securityAccessProvider).value;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
      if (done != null) messenger.showSnackBar(SnackBar(content: Text(done)));
    } on Object catch (error) {
      if (mounted) setState(() => _error = securityError(l, error, failed, access: access));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _addSite() async {
    final l = AppLocalizations.of(context);
    final origin = _origin.text.trim();
    if (origin.isEmpty) return;
    Verification? created;
    await _run(() async {
      created = await _repo.addSite(origin);
      _origin.clear();
      ref.invalidate(securityTargetsProvider);
    }, l.securityLab_targetError, done: l.securityLab_verificationCreated);
    if (created != null && mounted) await _showVerification(created!, origin);
  }

  Future<void> _showVerification(Verification v, String origin) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _VerifySheet(verification: v, origin: origin, reverifyDays: ref.read(securityAccessProvider).value?.reverifyDays ?? 0),
    );
    ref.invalidate(securityTargetsProvider);
    ref.invalidate(securityAccessProvider);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final access = ref.watch(securityAccessProvider);
    return Scaffold(
      appBar: AppBar(
        title: Text(l.securityLab_eyebrow, overflow: TextOverflow.ellipsis),
        actions: [
          IconButton(
            tooltip: l.securityLab_refresh,
            icon: const Icon(Icons.refresh),
            onPressed: () {
              ref.invalidate(securityAccessProvider);
              ref.invalidate(securityTargetsProvider);
              ref.invalidate(securityScansProvider);
            },
          ),
        ],
      ),
      body: access.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ListView(children: [
          if (e is ApiException && e.statusCode == 403) _upgrade(l) else Padding(padding: const EdgeInsets.all(16), child: Notice(text: l.securityLab_loadError, tone: NoticeTone.error)),
        ]),
        data: (a) {
          if (!a.enabled) return ListView(children: [EmptyState(icon: Icons.pause_circle_outline, title: l.securityLab_eyebrow, message: l.securityLab_disabledCopy)]);
          if (!a.canRead) return ListView(children: [_upgrade(l)]);
          return _body(l, a);
        },
      ),
    );
  }

  Widget _upgrade(AppLocalizations l) => EmptyState(
        icon: Icons.shield_outlined,
        title: l.securityLab_upgradeTitle,
        message: [
          l.securityLab_upgradeCopy,
          '• ${l.securityLab_upgradePointVerify}',
          '• ${l.securityLab_upgradePointScan}',
          '• ${l.securityLab_upgradePointFindings}',
        ].join('\n'),
      );

  Widget _body(AppLocalizations l, SecurityLabAccess a) {
    final theme = Theme.of(context);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    final targets = ref.watch(securityTargetsProvider);
    final scans = ref.watch(securityScansProvider);
    final verified = (targets.value ?? const <SecurityTarget>[]).where((t) => t.verified && !t.removed).toList();
    final targetId = verified.any((t) => t.id == _targetId) ? _targetId : (verified.isEmpty ? null : verified.first.id);
    final profile = a.profiles.contains(_profile) ? _profile : (a.profiles.isEmpty ? null : a.profiles.first);
    final originOf = {for (final t in targets.value ?? const <SecurityTarget>[]) t.id: t.origin};
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          Chip(label: Text('${l.securityLab_verifiedTargets}: ${l.securityLab_usageOf(a.verifiedTargets, a.maxTargets)}')),
          Chip(label: Text('${l.securityLab_scansThisMonth}: ${l.securityLab_usageOf(a.scansThisMonth, a.maxScansPerMonth)}')),
        ]),
        if (!a.granted) Notice(text: '${l.securityLab_pastReports}. ${l.securityLab_pastReportsCopy}'),
        if (_error != null) ...[
          const SizedBox(height: 8),
          Notice(key: const Key('security-error'), text: _error!, tone: NoticeTone.error),
        ],
        if (a.granted) ...[
          const SizedBox(height: 12),
          Text(l.securityLab_yourSites, style: theme.textTheme.titleMedium),
          Text(l.securityLab_yourSitesCopy, style: theme.textTheme.bodySmall),
          Row(children: [
            Expanded(
              child: TextField(
                key: const Key('security-origin'),
                controller: _origin,
                enabled: !_busy,
                keyboardType: TextInputType.url,
                textDirection: TextDirection.ltr,
                decoration: InputDecoration(labelText: l.securityLab_siteUrl, hintText: 'https://example.com'),
              ),
            ),
            const SizedBox(width: 8),
            FilledButton(
              key: const Key('security-add'),
              style: FilledButton.styleFrom(minimumSize: const Size(0, 52)),
              onPressed: _busy ? null : _addSite,
              child: Text(l.securityLab_addSite),
            ),
          ]),
        ],
        const SizedBox(height: 8),
        AsyncView(
          value: targets,
          onRetry: () => ref.invalidate(securityTargetsProvider),
          builder: (rows) {
            final live = rows.where((t) => !t.removed).toList();
            if (live.isEmpty) return Text(l.securityLab_noSites, style: theme.textTheme.bodySmall);
            return Column(children: [
              for (final t in live)
                Card(
                  key: Key('security-target-${t.id}'),
                  child: ListTile(
                    title: Text(t.origin, textDirection: TextDirection.ltr),
                    subtitle: Text(t.verified ? l.securityLab_targetStatus_verified : l.securityLab_targetStatus_pending),
                    trailing: Wrap(spacing: 2, children: [
                      if (!t.verified && a.granted)
                        TextButton(
                          key: Key('security-verify-${t.id}'),
                          onPressed: _busy
                              ? null
                              : () => _run(() async {
                                    final v = await _repo.addSite(t.origin);
                                    if (mounted) await _showVerification(v, t.origin);
                                  }, l.securityLab_targetError),
                          child: Text(l.securityLab_newInstructions),
                        ),
                      IconButton(
                        tooltip: l.securityLab_remove,
                        icon: const Icon(Icons.delete_outline),
                        onPressed: _busy
                            ? null
                            : () async {
                                final ok = await showDialog<bool>(
                                  context: context,
                                  builder: (context) => AlertDialog(
                                    content: Text(l.securityLab_removeConfirm(t.origin)),
                                    actions: [
                                      TextButton(onPressed: () => Navigator.pop(context, false), child: Text(l.securityLab_cancel)),
                                      FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(l.securityLab_remove)),
                                    ],
                                  ),
                                );
                                if (ok != true) return;
                                await _run(() async {
                                  await _repo.remove(t.id);
                                  ref.invalidate(securityTargetsProvider);
                                }, l.securityLab_removeError, done: l.securityLab_siteRemoved);
                              },
                      ),
                    ]),
                  ),
                ),
            ]);
          },
        ),
        if (a.granted) ...[
          const Divider(height: 28),
          Text(l.securityLab_startValidation, style: theme.textTheme.titleMedium),
          Text(l.securityLab_startValidationSubscriberCopy, style: theme.textTheme.bodySmall),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            key: const Key('security-target'),
            isExpanded: true,
            initialValue: targetId,
            decoration: InputDecoration(labelText: l.securityLab_selectTarget),
            items: [for (final t in verified) DropdownMenuItem(value: t.id, child: Text(t.origin))],
            onChanged: (v) => setState(() => _targetId = v),
          ),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            key: const Key('security-profile'),
            isExpanded: true,
            initialValue: profile,
            decoration: InputDecoration(labelText: l.securityLab_profile),
            items: [for (final p in a.profiles) DropdownMenuItem(value: p, child: Text(profileLabel(l, p)))],
            onChanged: (v) => setState(() => _profile = v),
          ),
          const SizedBox(height: 8),
          FilledButton.icon(
            key: const Key('security-scan'),
            onPressed: _busy || targetId == null || profile == null
                ? null
                : () => _run(() async {
                      final scan = await _repo.startScan(targetId, profile);
                      ref.invalidate(securityScansProvider);
                      ref.invalidate(securityAccessProvider);
                      if (mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.securityLab_scanQueued(scan.id.substring(0, 8)))));
                      }
                    }, l.securityLab_scanError),
            icon: const Icon(Icons.radar),
            label: Text(l.securityLab_queueValidation),
          ),
        ],
        const Divider(height: 28),
        Text(l.securityLab_recentScans, style: theme.textTheme.titleMedium),
        AsyncView(
          value: scans,
          onRetry: () => ref.invalidate(securityScansProvider),
          builder: (rows) => rows.isEmpty
              ? Text(l.securityLab_noScans, style: theme.textTheme.bodySmall)
              : Column(children: [
                  for (final s in rows)
                    Card(
                      key: Key('security-scan-${s.id}'),
                      child: ListTile(
                        title: Text(originOf[s.targetId] ?? s.targetId, textDirection: TextDirection.ltr),
                        subtitle: Text([
                          profileLabel(l, s.profile),
                          scanStatusLabel(l, s.status),
                          if (s.createdAt != null) format.format(s.createdAt!.toLocal()),
                          if (s.status == 'completed')
                            [for (final k in _severityOrder) if ((s.severity[k] ?? 0) > 0) '${severityLabel(l, k)} ${s.severity[k]}'].join(', '),
                          ?s.errorMessage,
                        ].where((x) => x.isNotEmpty).join(' · ')),
                        trailing: s.isActive
                            ? TextButton(
                                key: Key('security-cancel-${s.id}'),
                                onPressed: _busy
                                    ? null
                                    : () => _run(() async {
                                          await _repo.cancel(s.id);
                                          ref.invalidate(securityScansProvider);
                                        }, l.securityLab_cancelError, done: l.securityLab_scanCancelled),
                                child: Text(l.securityLab_cancel),
                              )
                            : s.status == 'completed'
                                ? TextButton(
                                    key: Key('security-view-${s.id}'),
                                    onPressed: () => context.push('/security-lab/scans/${Uri.encodeComponent(s.id)}?origin=${Uri.encodeQueryComponent(originOf[s.targetId] ?? '')}'),
                                    child: Text(l.securityLab_view),
                                  )
                                : null,
                      ),
                    ),
                ]),
        ),
        if (a.granted && a.source != 'subscription') ...[
          const SizedBox(height: 16),
          _ToolsCard(),
        ],
        if (a.granted) _RemediationsCard(),
      ],
    );
  }
}

/// Scanner engines and what each may do (not shown to subscribers, as on the website).
class _ToolsCard extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final tools = ref.watch(securityToolsProvider).value ?? const <SecurityTool>[];
    if (tools.isEmpty) return const SizedBox.shrink();
    return Card(
      key: const Key('security-tools'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(l.securityLab_engineInventory, style: theme.textTheme.titleMedium),
          Text(l.securityLab_engineInventoryCopy, style: theme.textTheme.bodySmall),
          const SizedBox(height: 8),
          for (final t in tools)
            ListTile(
              key: Key('security-tool-${t.id}'),
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: Icon(t.available ? Icons.check_circle_outline : Icons.remove_circle_outline),
              title: Text(t.id),
              subtitle: Text([
                t.category,
                t.available ? l.securityLab_available : l.securityLab_unavailable,
                t.requiresClone
                    ? l.securityLab_cloneOnly
                    : t.active
                        ? l.securityLab_authorizedRuntime
                        : l.securityLab_sourcePassive,
              ].join(' · ')),
            ),
        ]),
      ),
    );
  }
}

String remediationStatusLabel(AppLocalizations l, String s) => switch (s) {
      'regression_passed' => l.app_remediationReadyToRetest,
      'retest_queued' => l.app_remediationRetesting,
      'verified_fixed' || 'fixed' => l.app_remediationFixed,
      _ => s.replaceAll('_', ' '),
    };

/// Remediation requests: the retest and the final check are separate, evidence-gated steps.
class _RemediationsCard extends ConsumerStatefulWidget {
  @override
  ConsumerState<_RemediationsCard> createState() => _RemediationsCardState();
}

class _RemediationsCardState extends ConsumerState<_RemediationsCard> {
  bool _busy = false;

  Future<void> _run(Future<void> Function() action, String done) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      await action();
      messenger.showSnackBar(SnackBar(content: Text(done)));
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(securityError(l, error, l.securityLab_loadError))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    ref.invalidate(securityRemediationsProvider);
    ref.invalidate(securityScansProvider);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final rows = ref.watch(securityRemediationsProvider).value ?? const <SecurityRemediation>[];
    if (rows.isEmpty) return const SizedBox.shrink();
    final repo = ref.read(securityLabRepositoryProvider);
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Card(
        key: const Key('security-remediations'),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(l.securityLab_remediations, style: theme.textTheme.titleMedium),
            Text(l.securityLab_remediationsCopy, style: theme.textTheme.bodySmall),
            for (final r in rows.take(20))
              ListTile(
                key: Key('remediation-${r.id}'),
                contentPadding: EdgeInsets.zero,
                title: Text(remediationStatusLabel(l, r.status)),
                subtitle: Text(r.findingId.length > 8 ? r.findingId.substring(0, 8) : r.findingId),
                trailing: r.canRetest
                    ? TextButton(
                        key: Key('remediation-retest-${r.id}'),
                        onPressed: _busy ? null : () => _run(() => repo.retest(r.id), l.app_remediationRetestQueued),
                        child: Text(l.app_remediationRetest),
                      )
                    : r.canFinalize
                        ? TextButton(
                            key: Key('remediation-finalize-${r.id}'),
                            onPressed: _busy ? null : () => _run(() => repo.finalize(r.id), l.app_remediationFinalized),
                            child: Text(l.app_remediationFinalize),
                          )
                        : null,
              ),
          ]),
        ),
      ),
    );
  }
}

class _VerifySheet extends ConsumerStatefulWidget {
  const _VerifySheet({required this.verification, required this.origin, required this.reverifyDays});
  final Verification verification;
  final String origin;
  final int reverifyDays;

  @override
  ConsumerState<_VerifySheet> createState() => _VerifySheetState();
}

class _VerifySheetState extends ConsumerState<_VerifySheet> {
  String _method = 'http_file';
  bool _busy = false;
  String? _error;

  Widget _copyBox(String label, String value) {
    final l = AppLocalizations.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: Theme.of(context).textTheme.labelSmall),
        Row(children: [
          Expanded(child: SelectableText(value, textDirection: TextDirection.ltr, style: const TextStyle(fontFamily: 'monospace'))),
          IconButton(
            tooltip: l.securityLab_copy,
            icon: const Icon(Icons.copy),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: value));
              if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.securityLab_copied)));
            },
          ),
        ]),
      ]),
    );
  }

  Future<void> _verify() async {
    final l = AppLocalizations.of(context);
    final access = ref.read(securityAccessProvider).value;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(securityLabRepositoryProvider).verify(widget.verification.targetId, widget.verification.challenge, _method);
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.securityLab_verificationPassed)));
    } on Object catch (error) {
      if (mounted) setState(() => _error = securityError(l, error, l.securityLab_verificationError, access: access));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final v = widget.verification;
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.viewInsetsOf(context).bottom + 20),
      child: SingleChildScrollView(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(l.securityLab_verifyOwnership(widget.origin), style: theme.textTheme.titleLarge),
          Text(l.securityLab_chooseMethod, style: theme.textTheme.bodySmall),
          const SizedBox(height: 8),
          SegmentedButton<String>(
            segments: [
              ButtonSegment(value: 'http_file', label: Text(l.securityLab_methodFile)),
              ButtonSegment(value: 'dns_txt', label: Text(l.securityLab_methodDns), enabled: v.dnsAvailable),
            ],
            selected: {_method},
            onSelectionChanged: (s) => setState(() => _method = s.first),
          ),
          if (_method == 'http_file') ...[
            const SizedBox(height: 8),
            Text(l.securityLab_methodFileCopy, style: theme.textTheme.bodySmall),
            _copyBox(l.securityLab_fileUrl, v.fileUrl),
            _copyBox(l.securityLab_fileContent, v.fileContent),
          ] else ...[
            const SizedBox(height: 8),
            Text(l.securityLab_methodDnsCopy, style: theme.textTheme.bodySmall),
            _copyBox(l.securityLab_recordType, 'TXT'),
            _copyBox(l.securityLab_recordName, v.dnsName ?? ''),
            _copyBox(l.securityLab_recordValue, v.dnsValue),
            Text(l.securityLab_dnsPropagation, style: theme.textTheme.bodySmall),
          ],
          if (!v.dnsAvailable) Text(l.securityLab_dnsUnavailable, style: theme.textTheme.bodySmall),
          if (widget.reverifyDays > 0) ...[
            const SizedBox(height: 8),
            Text(l.securityLab_reverifyNote(widget.reverifyDays), style: theme.textTheme.bodySmall),
          ],
          if (_error != null) ...[
            const SizedBox(height: 8),
            Notice(key: const Key('verify-error'), text: _error!, tone: NoticeTone.error),
          ],
          const SizedBox(height: 12),
          FilledButton(key: const Key('security-verify-now'), onPressed: _busy ? null : _verify, child: Text(l.securityLab_verifyNow)),
          TextButton(onPressed: () => Navigator.pop(context), child: Text(l.securityLab_later)),
        ]),
      ),
    );
  }
}

/// One completed scan's findings, grouped by severity, with how to fix them.
class SecurityScanPage extends ConsumerWidget {
  const SecurityScanPage({super.key, required this.scanId, required this.origin});
  final String scanId;
  final String origin;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final access = ref.watch(securityAccessProvider).value;
    final report = (access?.reportsAvailable ?? false) || (access?.granted ?? false)
        ? ref.watch(securityReportProvider(scanId)).value
        : null;
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    final findingsNow = ref.watch(securityFindingsProvider(scanId)).value;
    return Scaffold(
      appBar: AppBar(
        title: Text(l.securityLab_reportTitle),
        actions: [
          if (findingsNow != null)
            IconButton(
              key: const Key('security-copy-report'),
              tooltip: l.app_copyReport,
              icon: const Icon(Icons.copy_all_outlined),
              onPressed: () async {
                final lines = <String>[
                  l.securityLab_reportTitle,
                  if ((report?.origin ?? origin).isNotEmpty) '${l.securityLab_target}: ${report?.origin ?? origin}',
                  if (report != null) '${l.securityLab_profile}: ${profileLabel(l, report.profile)}',
                  if (report?.completedAt != null) '${l.securityLab_reportCompleted}: ${format.format(report!.completedAt!.toLocal())}',
                  '',
                  for (final level in _severityOrder)
                    for (final f in findingsNow.where((x) => x.severity == level)) ...[
                      '[${severityLabel(l, f.severity)}] ${f.title}${f.cwe == null ? '' : ' (${f.cwe})'}',
                      if (f.location != null) '  ${f.location}',
                      '  ${l.securityLab_howToFix}: ${f.remediation ?? l.securityLab_noRemediation}',
                    ],
                  '',
                  l.securityLab_reportDisclaimer,
                ];
                await Clipboard.setData(ClipboardData(text: lines.join('\n')));
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.app_reportCopied)));
                }
              },
            ),
        ],
      ),
      body: AsyncView(
        value: ref.watch(securityFindingsProvider(scanId)),
        onRetry: () => ref.invalidate(securityFindingsProvider(scanId)),
        builder: (findings) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if ((report?.origin ?? origin).isNotEmpty)
              Text(report?.origin ?? origin, textDirection: TextDirection.ltr, style: theme.textTheme.titleMedium),
            if (report != null) ...[
              Text(
                [
                  '${l.securityLab_profile}: ${profileLabel(l, report.profile)}',
                  if (report.completedAt != null) '${l.securityLab_reportCompleted}: ${format.format(report.completedAt!.toLocal())}',
                  if (report.generatedAt != null) '${l.securityLab_reportGenerated}: ${format.format(report.generatedAt!.toLocal())}',
                ].join('\n'),
                key: const Key('security-report-meta'),
                style: theme.textTheme.bodySmall,
              ),
              const SizedBox(height: 6),
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final level in _severityOrder)
                  Chip(
                    key: Key('security-count-$level'),
                    visualDensity: VisualDensity.compact,
                    label: Text('${severityLabel(l, level)} · ${report.counts[level] ?? 0}'),
                  ),
              ]),
            ],
            Text(l.securityLab_reportDisclaimer, style: theme.textTheme.bodySmall),
            const SizedBox(height: 8),
            if (findings.isEmpty) Text(l.securityLab_noFindings),
            for (final level in _severityOrder)
              for (final f in findings.where((x) => x.severity == level))
                Card(
                  key: Key('finding-${f.id}'),
                  child: ExpansionTile(
                    leading: Icon(Icons.warning_amber, color: switch (level) {
                      'critical' || 'high' => theme.colorScheme.error,
                      'medium' => Colors.orange,
                      _ => theme.colorScheme.onSurfaceVariant,
                    }),
                    title: Text(f.title),
                    subtitle: Text([severityLabel(l, f.severity), f.category, ?f.cwe].join(' · ')),
                    childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                    expandedCrossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (f.location != null) SelectableText(f.location!, textDirection: TextDirection.ltr, style: theme.textTheme.bodySmall),
                      const SizedBox(height: 6),
                      Text(l.securityLab_howToFix, style: theme.textTheme.labelLarge),
                      Text(f.remediation ?? l.securityLab_noRemediation),
                      if (f.state == 'confirmed' && (access?.granted ?? false))
                        Align(
                          alignment: AlignmentDirectional.centerEnd,
                          child: TextButton.icon(
                            key: Key('finding-fix-${f.id}'),
                            icon: const Icon(Icons.build_outlined),
                            label: Text(l.app_remediationRequest),
                            onPressed: () async {
                              final messenger = ScaffoldMessenger.of(context);
                              try {
                                await ref.read(securityLabRepositoryProvider).requestRemediation(f.id);
                                messenger.showSnackBar(SnackBar(content: Text(l.app_remediationRequested)));
                              } on Object catch (error) {
                                messenger.showSnackBar(
                                  SnackBar(content: Text(securityError(l, error, l.app_remediationUnavailable))),
                                );
                              }
                              ref.invalidate(securityRemediationsProvider);
                            },
                          ),
                        ),
                    ],
                  ),
                ),
          ],
        ),
      ),
    );
  }
}
