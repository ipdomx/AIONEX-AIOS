import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../auth/password_recovery_pages.dart';
import '../workspace/workspace_models.dart';
import '../workspace/workspace_repository.dart';

String projectStatusLabel(AppLocalizations l, String status) => switch (status) {
      'planning' => l.projects_status_planning,
      'active' => l.projects_status_active,
      'in_progress' => l.projects_status_in_progress,
      'completed' => l.projects_status_completed,
      'paused' => l.projects_status_paused,
      'cancelled' => l.projects_status_cancelled,
      _ => status,
    };

String priorityLabel(AppLocalizations l, String priority) => switch (priority) {
      'low' => l.projects_priorityValue_low,
      'high' => l.projects_priorityValue_high,
      'critical' => l.projects_priorityValue_critical,
      _ => l.projects_priorityValue_medium,
    };

class ProjectsPage extends ConsumerWidget {
  const ProjectsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final projects = ref.watch(projectsProvider);
    return Scaffold(
      appBar: AppBar(
        title: Text(l.projects_title),
        actions: [
          IconButton(
            tooltip: l.projects_refresh,
            onPressed: () => ref.invalidate(projectsProvider),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('new-project'),
        onPressed: () => showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          showDragHandle: true,
          builder: (_) => const _CreateProjectSheet(),
        ),
        icon: const Icon(Icons.add),
        label: Text(l.projects_newProject),
      ),
      body: AsyncView(
        value: projects,
        onRetry: () => ref.invalidate(projectsProvider),
        builder: (items) {
          final visible = items.where((p) => p.isActive).toList();
          if (visible.isEmpty) {
            return ListView(
              children: [
                EmptyState(icon: Icons.folder_open, title: l.projects_emptyTitle, message: l.projects_emptyCopy),
              ],
            );
          }
          return RefreshIndicator(
            onRefresh: () => ref.refresh(projectsProvider.future),
            child: ListView.separated(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
              itemCount: visible.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (context, index) => _ProjectCard(project: visible[index]),
            ),
          );
        },
      ),
    );
  }
}

class _ProjectCard extends StatelessWidget {
  const _ProjectCard({required this.project});

  final Project project;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(child: Text(project.name, style: theme.textTheme.titleMedium)),
                StatusChip(
                  label: projectStatusLabel(l, project.status),
                  positive: project.status == 'completed',
                ),
              ],
            ),
            if (project.description.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(project.description, maxLines: 3, overflow: TextOverflow.ellipsis),
            ],
            const SizedBox(height: 10),
            LinearProgressIndicator(value: project.progress.clamp(0, 100) / 100, minHeight: 6),
            const SizedBox(height: 6),
            Text(
              '${l.projects_progress(project.progress)} · ${l.projects_tasks(project.taskCount)} · '
              '${priorityLabel(l, project.priority)} · ${project.workspace}',
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            if (project.tags.isNotEmpty) ...[
              const SizedBox(height: 8),
              Wrap(spacing: 6, runSpacing: 6, children: [for (final tag in project.tags) Chip(label: Text(tag))]),
            ],
            Align(
              alignment: AlignmentDirectional.centerEnd,
              child: TextButton.icon(
                onPressed: () => context.go('/conversations?project=${Uri.encodeComponent(project.id)}'),
                icon: const Icon(Icons.forum_outlined),
                label: Text(l.projects_openConversations),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CreateProjectSheet extends ConsumerStatefulWidget {
  const _CreateProjectSheet();

  @override
  ConsumerState<_CreateProjectSheet> createState() => _CreateProjectSheetState();
}

class _CreateProjectSheetState extends ConsumerState<_CreateProjectSheet> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _description = TextEditingController();
  final _tags = TextEditingController();
  late final Future<List<Workspace>> _workspaces = ref.read(workspaceRepositoryProvider).workspaces();
  String? _workspaceId;
  String _priority = 'medium';
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _description.dispose();
    _tags.dispose();
    super.dispose();
  }

  List<String> get _tagList =>
      _tags.text.split(',').map((tag) => tag.trim()).where((tag) => tag.isNotEmpty).toSet().take(12).toList();

  Future<void> _create() async {
    if (_busy || !(_formKey.currentState?.validate() ?? false) || _workspaceId == null) return;
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(workspaceRepositoryProvider).createProject(
            name: _name.text,
            workspaceId: _workspaceId!,
            priority: _priority,
            description: _description.text,
            tags: _tagList,
          );
      ref.invalidate(projectsProvider);
      ref.invalidate(quotaProvider);
      if (mounted) Navigator.of(context).pop();
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(l, error, l.projects_createError));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.viewInsetsOf(context).bottom + 20),
      child: FutureBuilder<List<Workspace>>(
        future: _workspaces,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const SizedBox(height: 160, child: Center(child: CircularProgressIndicator()));
          }
          final workspaces = snapshot.data ?? const <Workspace>[];
          if (workspaces.isEmpty) {
            return Padding(
              padding: const EdgeInsets.all(12),
              child: Notice(text: l.projects_noWorkspace, tone: NoticeTone.error),
            );
          }
          _workspaceId ??= workspaces.first.id;
          return Form(
            key: _formKey,
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(l.projects_createTitle, style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const Key('project-name'),
                    controller: _name,
                    enabled: !_busy,
                    maxLength: 160,
                    decoration: InputDecoration(labelText: l.projects_name),
                    validator: (value) => (value?.trim().length ?? 0) >= 2 ? null : l.projects_name,
                  ),
                  if (workspaces.length > 1) ...[
                    DropdownButtonFormField<String>(
                      initialValue: _workspaceId,
                      decoration: InputDecoration(labelText: l.projects_workspace),
                      items: [
                        for (final workspace in workspaces)
                          DropdownMenuItem(value: workspace.id, child: Text(workspace.name)),
                      ],
                      onChanged: _busy ? null : (value) => setState(() => _workspaceId = value),
                    ),
                    const SizedBox(height: 12),
                  ],
                  DropdownButtonFormField<String>(
                    initialValue: _priority,
                    decoration: InputDecoration(labelText: l.projects_priority),
                    items: [
                      for (final value in const ['low', 'medium', 'high', 'critical'])
                        DropdownMenuItem(value: value, child: Text(priorityLabel(l, value))),
                    ],
                    onChanged: _busy ? null : (value) => setState(() => _priority = value ?? 'medium'),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _description,
                    enabled: !_busy,
                    minLines: 2,
                    maxLines: 5,
                    decoration: InputDecoration(labelText: l.projects_projectDescription),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _tags,
                    enabled: !_busy,
                    decoration: InputDecoration(labelText: l.projects_tags, helperText: l.projects_tagsRule),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Notice(key: const Key('project-error'), text: _error!, tone: NoticeTone.error),
                  ],
                  const SizedBox(height: 16),
                  FilledButton(
                    key: const Key('project-create'),
                    onPressed: _busy ? null : _create,
                    child: Text(_busy ? l.projects_creating : l.projects_create),
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
