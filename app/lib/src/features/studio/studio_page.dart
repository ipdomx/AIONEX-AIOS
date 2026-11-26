import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart' show DateFormat;

import '../../../l10n/generated/app_localizations.dart';
import '../../core/files/file_share.dart';
import '../../widgets/async_view.dart';
import '../../widgets/error_text.dart';
import '../../widgets/notice.dart';
import '../auth/password_recovery_pages.dart';
import '../workspace/workspace_models.dart';
import '../workspace/workspace_repository.dart';
import 'studio_repository.dart';

String _size(int bytes) => bytes >= 1 << 20
    ? '${(bytes / (1 << 20)).toStringAsFixed(1)} MB'
    : bytes >= 1024
        ? '${(bytes / 1024).toStringAsFixed(0)} KB'
        : '$bytes B';

/// Production Studio: queue governed jobs, follow them live, use the assets.
class StudioPage extends ConsumerStatefulWidget {
  const StudioPage({super.key, this.pollInterval = const Duration(seconds: 4)});

  final Duration pollInterval;

  @override
  ConsumerState<StudioPage> createState() => _StudioPageState();
}

class _StudioPageState extends ConsumerState<StudioPage> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // Active work refreshes automatically, like the website's live queue.
    _timer = Timer.periodic(widget.pollInterval, (_) {
      final jobs = ref.read(studioJobsProvider).value;
      if (jobs != null && jobs.any((job) => job.isActive)) {
        ref.invalidate(studioJobsProvider);
        ref.invalidate(studioAssetsProvider);
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action, String done) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await action();
      messenger.showSnackBar(SnackBar(content: Text(done)));
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(describeAccountError(l, error, l.studio_actionError))));
    }
    ref.invalidate(studioJobsProvider);
    ref.invalidate(studioAssetsProvider);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(l.studio_title),
          actions: [
            IconButton(
              tooltip: l.studio_refresh,
              icon: const Icon(Icons.refresh),
              onPressed: () {
                ref.invalidate(studioJobsProvider);
                ref.invalidate(studioAssetsProvider);
              },
            ),
          ],
          bottom: TabBar(tabs: [Tab(text: l.studio_queueTitle), Tab(text: l.studio_assetLibrary)]),
        ),
        floatingActionButton: FloatingActionButton.extended(
          key: const Key('new-studio-job'),
          icon: const Icon(Icons.auto_awesome),
          label: Text(l.studio_createTitle),
          onPressed: () => showModalBottomSheet<void>(
            context: context,
            isScrollControlled: true,
            showDragHandle: true,
            builder: (_) => const _CreateJobSheet(),
          ),
        ),
        body: TabBarView(children: [_queue(l), _assets(l)]),
      ),
    );
  }

  Widget _queue(AppLocalizations l) {
    final jobs = ref.watch(studioJobsProvider);
    final theme = Theme.of(context);
    return AsyncView(
      value: jobs,
      onRetry: () => ref.invalidate(studioJobsProvider),
      builder: (items) => items.isEmpty
          ? ListView(children: [EmptyState(icon: Icons.auto_awesome, title: l.studio_emptyQueue, message: l.studio_queueCopy)])
          : RefreshIndicator(
              onRefresh: () => ref.refresh(studioJobsProvider.future),
              child: ListView.separated(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                itemCount: items.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (context, index) {
                  final job = items[index];
                  return Card(
                    key: Key('studio-job-${job.id}'),
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(children: [
                            Expanded(child: Text(job.title, style: theme.textTheme.titleMedium)),
                            StatusChip(
                              label: job.status,
                              positive: job.status == 'completed',
                              negative: job.status == 'failed' || job.status == 'blocked',
                            ),
                          ]),
                          const SizedBox(height: 4),
                          Text(
                            [
                              job.department,
                              '${l.studio_provider}: ${job.provider ?? l.studio_providerNeutral}',
                              '${l.studio_safety}: ${job.safetyStatus}',
                              if (job.costUsd != null && job.costUsd! > 0) '${l.studio_cost}: \$${job.costUsd!.toStringAsFixed(4)}',
                            ].join(' · '),
                            style: theme.textTheme.bodySmall,
                          ),
                          if (job.isActive) ...[
                            const SizedBox(height: 8),
                            LinearProgressIndicator(value: job.progress.clamp(0, 100) / 100),
                          ],
                          if (job.errorMessage != null && job.errorMessage!.isNotEmpty) ...[
                            const SizedBox(height: 6),
                            Text(job.errorMessage!, style: TextStyle(color: theme.colorScheme.error)),
                          ],
                          if (job.canRetry || job.canCancel)
                            Align(
                              alignment: AlignmentDirectional.centerEnd,
                              child: job.canRetry
                                  ? TextButton.icon(
                                      icon: const Icon(Icons.replay),
                                      label: Text(l.studio_retry),
                                      onPressed: () => _run(() => ref.read(studioRepositoryProvider).retry(job.id), l.studio_retryQueued),
                                    )
                                  : TextButton(
                                      onPressed: () async {
                                        final ok = await showDialog<bool>(
                                          context: context,
                                          builder: (context) => AlertDialog(
                                            content: Text(l.studio_cancelConfirm),
                                            actions: [
                                              TextButton(onPressed: () => Navigator.pop(context, false), child: Text(l.projects_cancel)),
                                              FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(l.studio_cancelJob)),
                                            ],
                                          ),
                                        );
                                        if (ok == true) {
                                          await _run(() => ref.read(studioRepositoryProvider).cancel(job.id), l.studio_cancelled);
                                        }
                                      },
                                      child: Text(l.studio_cancelJob),
                                    ),
                            ),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
    );
  }

  Widget _assets(AppLocalizations l) {
    final assets = ref.watch(studioAssetsProvider);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    return AsyncView(
      value: assets,
      onRetry: () => ref.invalidate(studioAssetsProvider),
      builder: (items) => items.isEmpty
          ? ListView(children: [EmptyState(icon: Icons.inventory_2_outlined, title: l.studio_emptyAssets, message: l.studio_assetLibraryCopy)])
          : RefreshIndicator(
              onRefresh: () => ref.refresh(studioAssetsProvider.future),
              child: ListView.separated(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                itemCount: items.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (context, index) {
                  final asset = items[index];
                  return Card(
                    key: Key('studio-asset-${asset.id}'),
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(asset.title, style: Theme.of(context).textTheme.titleMedium),
                          const SizedBox(height: 4),
                          Text(
                            [
                              asset.filename,
                              _size(asset.sizeBytes),
                              'v${asset.currentRevision}',
                              if (asset.updatedAt != null) format.format(asset.updatedAt!.toLocal()),
                            ].join(' · '),
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                          if (asset.attachedProjectIds.isNotEmpty)
                            Text(l.studio_attachedCount(asset.attachedProjectIds.length),
                                style: Theme.of(context).textTheme.bodySmall),
                          Wrap(spacing: 4, children: [
                            TextButton.icon(
                              key: Key('download-${asset.id}'),
                              icon: const Icon(Icons.download),
                              label: Text(l.studio_download),
                              onPressed: () => _run(() async {
                                final file = await ref.read(studioRepositoryProvider).download(asset);
                                await ref.read(fileSharerProvider)(file);
                              }, l.studio_downloadStarted),
                            ),
                            TextButton.icon(
                              icon: const Icon(Icons.history),
                              label: Text(l.studio_history),
                              onPressed: () => showModalBottomSheet<void>(
                                context: context,
                                showDragHandle: true,
                                builder: (_) => _HistorySheet(asset: asset),
                              ),
                            ),
                            TextButton.icon(
                              icon: const Icon(Icons.edit_note),
                              label: Text(l.studio_revision),
                              onPressed: () => showModalBottomSheet<void>(
                                context: context,
                                isScrollControlled: true,
                                showDragHandle: true,
                                builder: (_) => _RevisionSheet(asset: asset),
                              ),
                            ),
                            TextButton.icon(
                              icon: const Icon(Icons.link),
                              label: Text(l.studio_attach),
                              onPressed: () => showModalBottomSheet<void>(
                                context: context,
                                showDragHandle: true,
                                builder: (_) => _AttachSheet(asset: asset),
                              ),
                            ),
                          ]),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
    );
  }
}

class _CreateJobSheet extends ConsumerStatefulWidget {
  const _CreateJobSheet();

  @override
  ConsumerState<_CreateJobSheet> createState() => _CreateJobSheetState();
}

class _CreateJobSheetState extends ConsumerState<_CreateJobSheet> {
  final _formKey = GlobalKey<FormState>();
  final _title = TextEditingController();
  final _brief = TextEditingController();
  final _style = TextEditingController(text: 'professional');
  final _target = TextEditingController();
  final _language = TextEditingController();
  String? _department;
  String? _projectId;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_title, _brief, _style, _target, _language]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _queue(List<StudioDepartment> departments) async {
    final l = AppLocalizations.of(context);
    if (_busy || !(_formKey.currentState?.validate() ?? false) || _department == null) return;
    final department = departments.firstWhere((d) => d.id == _department);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(studioRepositoryProvider).createJob(
            department: department.id,
            title: _title.text,
            brief: _brief.text,
            language: Localizations.localeOf(context).languageCode,
            style: _style.text,
            target: _target.text,
            programmingLanguage: department.takesProgrammingLanguage ? _language.text : null,
            projectId: _projectId,
          );
      ref.invalidate(studioJobsProvider);
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.studio_queued)));
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(l, error, l.studio_actionError));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final departments = ref.watch(studioDepartmentsProvider);
    final projects = ref.watch(projectsProvider).value?.where((p) => p.isActive).toList() ?? const <Project>[];
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.viewInsetsOf(context).bottom + 20),
      child: AsyncView(
        value: departments,
        onRetry: () => ref.invalidate(studioDepartmentsProvider),
        builder: (items) {
          _department ??= items.firstOrNull?.id;
          final selected = items.where((d) => d.id == _department).firstOrNull;
          return Form(
            key: _formKey,
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(l.studio_createTitle, style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 14),
                  DropdownButtonFormField<String>(
                    key: const Key('studio-department'),
                    isExpanded: true,
                    initialValue: _department,
                    decoration: InputDecoration(labelText: l.studio_department),
                    items: [for (final d in items) DropdownMenuItem(value: d.id, child: Text(d.name))],
                    onChanged: _busy ? null : (v) => setState(() => _department = v),
                  ),
                  if (selected != null && selected.outputs.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Text(selected.outputs.join(' · '), style: Theme.of(context).textTheme.bodySmall),
                    ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String?>(
                    isExpanded: true,
                    initialValue: _projectId,
                    decoration: InputDecoration(labelText: l.studio_project),
                    items: [
                      DropdownMenuItem<String?>(child: Text(l.studio_projectOptional)),
                      for (final p in projects) DropdownMenuItem<String?>(value: p.id, child: Text(p.name)),
                    ],
                    onChanged: _busy ? null : (v) => setState(() => _projectId = v),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    key: const Key('studio-title'),
                    controller: _title,
                    enabled: !_busy,
                    maxLength: 240,
                    decoration: InputDecoration(labelText: l.studio_titleLabel),
                    validator: (v) => (v?.trim().length ?? 0) >= 3 ? null : l.studio_titleLabel,
                  ),
                  TextFormField(
                    key: const Key('studio-brief'),
                    controller: _brief,
                    enabled: !_busy,
                    minLines: 4,
                    maxLines: 10,
                    maxLength: 12000,
                    decoration: InputDecoration(labelText: l.studio_brief, alignLabelWithHint: true),
                    validator: (v) => (v?.trim().length ?? 0) >= 10 ? null : l.studio_brief,
                  ),
                  TextFormField(controller: _style, enabled: !_busy, decoration: InputDecoration(labelText: l.studio_style)),
                  const SizedBox(height: 12),
                  TextFormField(controller: _target, enabled: !_busy, decoration: InputDecoration(labelText: l.studio_target)),
                  if (selected?.takesProgrammingLanguage ?? false) ...[
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _language,
                      enabled: !_busy,
                      decoration: InputDecoration(labelText: l.studio_programmingLanguage),
                    ),
                  ],
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Notice(key: const Key('studio-error'), text: _error!, tone: NoticeTone.error),
                  ],
                  const SizedBox(height: 16),
                  FilledButton(
                    key: const Key('studio-queue'),
                    onPressed: _busy ? null : () => _queue(items),
                    child: Text(_busy ? l.studio_queueing : l.studio_queue),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _HistorySheet extends ConsumerWidget {
  const _HistorySheet({required this.asset});

  final StudioAsset asset;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final format = DateFormat.yMMMd(Localizations.localeOf(context).toLanguageTag()).add_Hm();
    return FutureBuilder<List<StudioRevision>>(
      future: ref.read(studioRepositoryProvider).revisions(asset.id),
      builder: (context, snapshot) {
        if (snapshot.hasError) return Padding(padding: const EdgeInsets.all(24), child: Text(l.studio_historyError));
        if (!snapshot.hasData) return const SizedBox(height: 120, child: Center(child: CircularProgressIndicator()));
        return ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          children: [
            Text(asset.title, style: Theme.of(context).textTheme.titleMedium),
            for (final revision in snapshot.data!)
              ListTile(
                leading: CircleAvatar(child: Text('${revision.number}')),
                title: Text(revision.filename),
                subtitle: Text([
                  if (revision.changeNote != null && revision.changeNote!.isNotEmpty) revision.changeNote!,
                  if (revision.createdAt != null) format.format(revision.createdAt!.toLocal()),
                ].join('\n')),
              ),
          ],
        );
      },
    );
  }
}

class _RevisionSheet extends ConsumerStatefulWidget {
  const _RevisionSheet({required this.asset});

  final StudioAsset asset;

  @override
  ConsumerState<_RevisionSheet> createState() => _RevisionSheetState();
}

class _RevisionSheetState extends ConsumerState<_RevisionSheet> {
  final _brief = TextEditingController();
  final _note = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _brief.dispose();
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.viewInsetsOf(context).bottom + 20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(l.studio_revision, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          TextField(
            controller: _brief,
            minLines: 3,
            maxLines: 8,
            decoration: InputDecoration(labelText: l.studio_revisionPrompt, alignLabelWithHint: true),
          ),
          const SizedBox(height: 12),
          TextField(controller: _note, decoration: InputDecoration(labelText: l.studio_revisionNotePrompt)),
          if (_error != null) ...[const SizedBox(height: 10), Notice(text: _error!, tone: NoticeTone.error)],
          const SizedBox(height: 14),
          FilledButton(
            onPressed: _busy
                ? null
                : () async {
                    if (_brief.text.trim().length < 10 || _note.text.trim().isEmpty) return;
                    setState(() => _busy = true);
                    try {
                      await ref.read(studioRepositoryProvider).createRevision(widget.asset.id, brief: _brief.text, changeNote: _note.text);
                      ref.invalidate(studioJobsProvider);
                      if (!context.mounted) return;
                      Navigator.of(context).pop();
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.studio_revisionQueued)));
                    } on Object catch (error) {
                      if (mounted) setState(() => _error = describeAccountError(l, error, l.studio_actionError));
                    } finally {
                      if (mounted) setState(() => _busy = false);
                    }
                  },
            child: Text(l.studio_queue),
          ),
        ],
      ),
    );
  }
}

class _AttachSheet extends ConsumerWidget {
  const _AttachSheet({required this.asset});

  final StudioAsset asset;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final projects = ref.watch(projectsProvider);
    return AsyncView(
      value: projects,
      onRetry: () => ref.invalidate(projectsProvider),
      builder: (items) => ListView(
        shrinkWrap: true,
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
        children: [
          Text(l.studio_attach, style: Theme.of(context).textTheme.titleMedium),
          for (final project in items.where((p) => p.isActive))
            ListTile(
              title: Text(project.name),
              trailing: asset.attachedProjectIds.contains(project.id) ? const Icon(Icons.check) : null,
              onTap: () async {
                final messenger = ScaffoldMessenger.of(context);
                final navigator = Navigator.of(context);
                try {
                  await ref.read(studioRepositoryProvider).attach(asset.id, project.id);
                  ref.invalidate(studioAssetsProvider);
                  navigator.pop();
                  messenger.showSnackBar(SnackBar(content: Text(l.studio_attached)));
                } on Object catch (error) {
                  messenger.showSnackBar(SnackBar(content: Text(describeError(l, error))));
                }
              },
            ),
        ],
      ),
    );
  }
}
