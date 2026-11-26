import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_client.dart';
import '../../core/auth/session_controller.dart';
import '../../core/files/file_share.dart';
import '../../core/providers.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../auth/password_recovery_pages.dart';
import '../workspace/workspace_models.dart';

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;
Map<String, Object?> _map(Object? v) => v is Map ? v.cast<String, Object?>() : const {};

const ownerApprovalFinding = 'owner approval is required';

@immutable
class ProjectExecution {
  const ProjectExecution({
    required this.id,
    required this.mode,
    required this.status,
    required this.stage,
    required this.progress,
    required this.approved,
    required this.readiness,
    required this.costUsd,
    required this.requests,
    required this.tokens,
    required this.blockingFindings,
    required this.evidenceAvailable,
    required this.errorMessage,
  });

  final String id;
  final String mode;
  final String status;
  final String stage;
  final int progress;
  final bool approved;
  final double? readiness;
  final double? costUsd;
  final int requests;
  final int tokens;
  final List<String> blockingFindings;
  final bool evidenceAvailable;
  final String? errorMessage;

  bool get isActive => status == 'queued' || status == 'running';

  /// Everything passed and only the Organization Owner's sign-off is left (same rule as the website).
  bool get waitsForOwner =>
      status == 'completed' && !approved && blockingFindings.length == 1 && blockingFindings.first == ownerApprovalFinding;

  factory ProjectExecution.fromJson(Map<String, Object?> j) {
    final result = _map(j['result']);
    final findings = result['blocking_findings'];
    return ProjectExecution(
      id: _s(j['id']),
      mode: _s(j['mode']),
      status: _s(j['status']),
      stage: _s(j['stage']),
      progress: _i(j['progress']),
      approved: j['approved'] == true,
      readiness: j['readiness_score'] is num ? (j['readiness_score']! as num).toDouble() : null,
      costUsd: j['calculated_cost_usd'] is num ? (j['calculated_cost_usd']! as num).toDouble() : null,
      requests: _i(j['requests_count']),
      tokens: _i(j['total_tokens']),
      blockingFindings: findings is List ? findings.whereType<String>().toList() : const [],
      evidenceAvailable: j['evidence_available'] == true,
      errorMessage: j['error_message'] as String?,
    );
  }
}

/// The governed project cycle, the same endpoints as the website's projects page.
class ExecutionRepository {
  ExecutionRepository(this._api);
  final ApiClient _api;

  String _base(String projectId) => '/projects/${Uri.encodeComponent(projectId)}/executions';

  Future<ProjectExecution?> latest(String projectId) async {
    final rows = await _api.getList(_base(projectId), query: {'limit': 1});
    return rows.isNotEmpty && rows.first is Map ? ProjectExecution.fromJson((rows.first! as Map).cast<String, Object?>()) : null;
  }

  /// [externalAllowed] is false on the free plan, which runs on AIOS's local model.
  Future<ProjectExecution> start(String projectId, {required String mode, required bool externalAllowed}) async =>
      ProjectExecution.fromJson(await _api.postJson(_base(projectId),
          body: {'mode': mode, 'confirm_external_processing': externalAllowed}, retry: false));

  Future<ProjectExecution> approve(String projectId, String executionId) async => ProjectExecution.fromJson(await _api.postJson(
        '${_base(projectId)}/${Uri.encodeComponent(executionId)}/approve',
        body: {'confirm_owner_approval': true, 'note': null},
        retry: false,
      ));

  Future<DownloadedFile> download(String projectId, String executionId) =>
      _api.download('${_base(projectId)}/${Uri.encodeComponent(executionId)}/download', fallbackName: 'aionex-delivery.zip');
}

final executionRepositoryProvider = Provider<ExecutionRepository>((ref) => ExecutionRepository(ref.watch(apiClientProvider)));
final latestExecutionProvider =
    FutureProvider.autoDispose.family<ProjectExecution?, String>((ref, id) => ref.watch(executionRepositoryProvider).latest(id));

String stageLabel(AppLocalizations l, String s) => switch (s) {
      'queued' => l.projects_execution_stage_queued,
      'intake' => l.projects_execution_stage_intake,
      'cognitive_review' => l.projects_execution_stage_cognitive_review,
      'constitutional_review' => l.projects_execution_stage_constitutional_review,
      'wisdom_deliberation' => l.projects_execution_stage_wisdom_deliberation,
      'government_review' => l.projects_execution_stage_government_review,
      'ministry_routing' => l.projects_execution_stage_ministry_routing,
      'external_research' => l.projects_execution_stage_external_research,
      'research_verification' => l.projects_execution_stage_research_verification,
      'provider_model_validation' => l.projects_execution_stage_provider_model_validation,
      'provider_execution' => l.projects_execution_stage_provider_execution,
      'provider_execution_completed' => l.projects_execution_stage_provider_execution_completed,
      'governed_plan_review' => l.projects_execution_stage_governed_plan_review,
      'plan_rework_required' => l.projects_execution_stage_plan_rework_required,
      'plan_approved_for_implementation' => l.projects_execution_stage_plan_approved_for_implementation,
      'implementation_specification' => l.projects_execution_stage_implementation_specification,
      'implementation_generation' => l.projects_execution_stage_implementation_generation,
      'implementation_tests' => l.projects_execution_stage_implementation_tests,
      'engineering_review' => l.projects_execution_stage_engineering_review,
      'security_review' => l.projects_execution_stage_security_review,
      'workforce_execution' => l.projects_execution_stage_workforce_execution,
      'integration_review' => l.projects_execution_stage_integration_review,
      'rollback_verification' => l.projects_execution_stage_rollback_verification,
      'release_review' => l.projects_execution_stage_release_review,
      'review' => l.projects_execution_stage_review,
      'rework_required' => l.projects_execution_stage_rework_required,
      'approved' => l.projects_execution_stage_approved,
      'completed' => l.projects_execution_stage_completed,
      'failed' => l.projects_execution_stage_failed,
      _ => s,
    };

/// The governed cycle card inside a project: start, follow live, approve, download.
class ExecutionPanel extends ConsumerStatefulWidget {
  const ExecutionPanel({super.key, required this.project, this.pollInterval = const Duration(seconds: 4)});

  final Project project;
  final Duration pollInterval;

  @override
  ConsumerState<ExecutionPanel> createState() => _ExecutionPanelState();
}

class _ExecutionPanelState extends ConsumerState<ExecutionPanel> {
  Timer? _timer;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(widget.pollInterval, (_) {
      final e = ref.read(latestExecutionProvider(widget.project.id)).value;
      if (e != null && e.isActive) ref.invalidate(latestExecutionProvider(widget.project.id));
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<bool> _confirm(String text) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) {
          final l = AppLocalizations.of(context);
          return AlertDialog(
            content: SingleChildScrollView(child: Text(text)),
            actions: [
              TextButton(onPressed: () => Navigator.pop(context, false), child: Text(l.projects_cancel)),
              FilledButton(key: const Key('execution-confirm'), onPressed: () => Navigator.pop(context, true), child: Text(l.projects_execution_start)),
            ],
          );
        },
      ) ==
      true;

  Future<void> _run(Future<void> Function() action, String failed) async {
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(l, error, failed));
    } finally {
      if (mounted) setState(() => _busy = false);
      ref.invalidate(latestExecutionProvider(widget.project.id));
      ref.invalidate(quotaProvider);
    }
  }

  Future<void> _start({required bool threeD}) async {
    final l = AppLocalizations.of(context);
    final session = ref.read(sessionProvider).value;
    final user = session is SignedIn ? session.user : null;
    final free = user == null || user.role.toLowerCase() == 'free user' || user.organizationPlan.toLowerCase() == 'free';
    final text = threeD
        ? l.projects_execution_threeDConfirm
        : free
            ? l.projects_execution_localConfirm
            : l.projects_execution_confirm('AIOS governed AI runtime', '0.05');
    if (!await _confirm(text)) return;
    await _run(
      () => ref
          .read(executionRepositoryProvider)
          .start(widget.project.id, mode: threeD ? '3d_full' : 'full', externalAllowed: threeD || !free),
      l.projects_execution_startError,
    );
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final session = ref.watch(sessionProvider).value;
    final isOwner = session is SignedIn && session.user.role == 'Owner';
    final repo = ref.read(executionRepositoryProvider);
    return AsyncView(
      value: ref.watch(latestExecutionProvider(widget.project.id)),
      onRetry: () => ref.invalidate(latestExecutionProvider(widget.project.id)),
      builder: (e) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(l.projects_execution_title, style: theme.textTheme.titleMedium),
        Text(l.projects_execution_description, style: theme.textTheme.bodySmall),
        const SizedBox(height: 8),
        if (e != null) ...[
          Row(children: [
            Expanded(child: Text('${l.projects_execution_stageLabel}: ${stageLabel(l, e.stage)}')),
            StatusChip(
              label: switch (e.status) {
                'queued' => l.projects_execution_status_queued,
                'running' => l.projects_execution_status_running,
                'completed' => l.projects_execution_status_completed,
                _ => l.projects_execution_status_failed,
              },
              positive: e.status == 'completed',
              negative: e.status == 'failed',
            ),
          ]),
          if (e.isActive) ...[
            const SizedBox(height: 6),
            LinearProgressIndicator(value: e.progress > 0 ? e.progress.clamp(0, 100) / 100 : null),
            const SizedBox(height: 4),
            Text(l.projects_execution_runningNotice, style: theme.textTheme.bodySmall),
          ],
          Text(
            [
              '${l.projects_execution_readiness}: ${e.readiness == null ? '—' : '${(e.readiness! * 100).round()}%'}',
              '${l.projects_execution_cost}: \$${(e.costUsd ?? 0).toStringAsFixed(4)}',
              l.projects_execution_usage(e.requests, e.tokens),
            ].join(' · '),
            style: theme.textTheme.bodySmall,
          ),
          if (e.status == 'completed') ...[
            const SizedBox(height: 6),
            Text(
              e.approved
                  ? l.projects_execution_approved
                  : e.waitsForOwner
                      ? l.projects_execution_ownerApprovalRequired
                      : l.projects_execution_rework(e.blockingFindings.length),
              style: theme.textTheme.bodySmall,
            ),
            if (!e.waitsForOwner)
              for (final f in e.blockingFindings.take(12)) Text('• $f', style: theme.textTheme.bodySmall),
          ],
          if (e.status == 'failed') Text(e.errorMessage ?? l.projects_execution_failed, style: TextStyle(color: theme.colorScheme.error)),
        ],
        if (_error != null) ...[
          const SizedBox(height: 6),
          Notice(key: const Key('execution-error'), text: _error!, tone: NoticeTone.error),
        ],
        const SizedBox(height: 8),
        Wrap(spacing: 6, runSpacing: 6, children: [
          if (e != null && e.waitsForOwner && isOwner)
            FilledButton.icon(
              key: const Key('execution-approve'),
              style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
              onPressed: _busy
                  ? null
                  : () async {
                      if (!await _confirm(l.projects_execution_approvalConfirm)) return;
                      await _run(() => repo.approve(widget.project.id, e.id), l.projects_execution_approvalError);
                    },
              icon: const Icon(Icons.verified_outlined),
              label: Text(_busy ? l.projects_execution_approving : l.projects_execution_approve),
            ),
          if (e != null && e.evidenceAvailable)
            OutlinedButton.icon(
              key: const Key('execution-download'),
              style: OutlinedButton.styleFrom(minimumSize: const Size(0, 44)),
              onPressed: _busy
                  ? null
                  : () => _run(() async {
                        final file = await repo.download(widget.project.id, e.id);
                        await ref.read(fileSharerProvider)(file);
                      }, l.projects_execution_downloadError),
              icon: const Icon(Icons.download),
              label: Text(l.projects_execution_download),
            ),
          if (e == null || !e.isActive) ...[
            FilledButton.icon(
              key: const Key('execution-start'),
              style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
              onPressed: _busy ? null : () => _start(threeD: false),
              icon: const Icon(Icons.play_arrow),
              label: Text(_busy ? l.projects_execution_starting : (e == null ? l.projects_execution_start : l.projects_execution_newCycle)),
            ),
            OutlinedButton.icon(
              key: const Key('execution-start-3d'),
              style: OutlinedButton.styleFrom(minimumSize: const Size(0, 44)),
              onPressed: _busy ? null : () => _start(threeD: true),
              icon: const Icon(Icons.view_in_ar),
              label: Text(e == null ? l.projects_execution_threeDStart : l.projects_execution_threeDNewCycle),
            ),
          ],
        ]),
      ]),
    );
  }
}

/// One project: its governed cycle and a way into its 3D models and chats.
class ProjectDetailPage extends ConsumerWidget {
  const ProjectDetailPage({super.key, required this.projectId});
  final String projectId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final projects = ref.watch(projectsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(projects.value?.where((p) => p.id == projectId).firstOrNull?.name ?? l.projects_title)),
      body: AsyncView(
        value: projects,
        onRetry: () => ref.invalidate(projectsProvider),
        builder: (rows) {
          final project = rows.where((p) => p.id == projectId).firstOrNull;
          if (project == null) return Center(child: Text(l.projects_emptyTitle));
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (project.description.isNotEmpty) Text(project.description),
              const SizedBox(height: 12),
              ExecutionPanel(project: project),
            ],
          );
        },
      ),
    );
  }
}
