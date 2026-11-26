import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/auth/session_controller.dart';
import '../../core/files/file_share.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../auth/password_recovery_pages.dart';
import '../workspace/workspace_models.dart';
import 'academy_repository.dart';

/// Academy & Course Factory: courses, six-locale packages, review and download.
class AcademyPage extends ConsumerStatefulWidget {
  const AcademyPage({super.key, this.pollInterval = const Duration(seconds: 4)});

  final Duration pollInterval;

  @override
  ConsumerState<AcademyPage> createState() => _AcademyPageState();
}

class _AcademyPageState extends ConsumerState<AcademyPage> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // Packages that are still being built refresh on their own.
    _timer = Timer.periodic(widget.pollInterval, (_) {
      for (final course in ref.read(academyCoursesProvider).value ?? const <AcademyCourse>[]) {
        final packages = ref.read(academyPackagesProvider(course.id)).value;
        if (packages != null && packages.any((p) => p.isActive)) ref.invalidate(academyPackagesProvider(course.id));
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _refresh() {
    ref.invalidate(academyCoursesProvider);
    ref.invalidate(academyPackagesProvider);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final session = ref.watch(sessionProvider).value;
    final access = session is SignedIn ? AcademyAccess.of(session.user) : null;
    final Widget body;
    if (access == null) {
      body = const Center(child: CircularProgressIndicator());
    } else if (!access.paidPlan) {
      body = ListView(children: [EmptyState(icon: Icons.school_outlined, title: l.academyUser_planTitle, message: l.academyUser_planCopy)]);
    } else if (!access.canRead) {
      body = ListView(children: [
        EmptyState(icon: Icons.shield_outlined, title: l.academyUser_permissionTitle, message: l.academyUser_permissionCopy),
      ]);
    } else {
      body = _courses(l, access);
    }
    return Scaffold(
      appBar: AppBar(
        title: Text(l.app_academy),
        actions: [IconButton(tooltip: l.academyUser_refresh, icon: const Icon(Icons.refresh), onPressed: _refresh)],
      ),
      floatingActionButton: access != null && access.paidPlan && access.canWrite
          ? FloatingActionButton.extended(
              key: const Key('new-course'),
              icon: const Icon(Icons.add),
              label: Text(l.academyUser_createCourse),
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                isScrollControlled: true,
                showDragHandle: true,
                builder: (_) => const _CourseSheet(),
              ),
            )
          : null,
      body: body,
    );
  }

  Widget _courses(AppLocalizations l, AcademyAccess access) {
    final courses = ref.watch(academyCoursesProvider);
    return AsyncView(
      value: courses,
      onRetry: () => ref.invalidate(academyCoursesProvider),
      builder: (items) => items.isEmpty
          ? ListView(children: [EmptyState(icon: Icons.school_outlined, title: l.academyUser_emptyCourses, message: l.academyUser_description)])
          : RefreshIndicator(
              onRefresh: () async => _refresh(),
              child: ListView.separated(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                itemCount: items.length + 1,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (context, index) => index == 0
                    ? Text(l.academyUser_governedCopy, style: Theme.of(context).textTheme.bodySmall)
                    : _CourseCard(course: items[index - 1], access: access),
              ),
            ),
    );
  }
}

class _CourseCard extends ConsumerWidget {
  const _CourseCard({required this.course, required this.access});

  final AcademyCourse course;
  final AcademyAccess access;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final packages = ref.watch(academyPackagesProvider(course.id));
    return Card(
      key: Key('course-${course.id}'),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(course.title, style: theme.textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(
              [course.code, l.academyUser_version(course.version), l.academyUser_passing(course.passingScore.round())].join(' · '),
              style: theme.textTheme.bodySmall,
            ),
            if (course.description != null && course.description!.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(course.description!, maxLines: 3, overflow: TextOverflow.ellipsis),
            ],
            const Divider(height: 22),
            AsyncView(
              value: packages,
              onRetry: () => ref.invalidate(academyPackagesProvider(course.id)),
              builder: (rows) => Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (rows.isEmpty) Text(l.academyUser_noPackages, style: theme.textTheme.bodySmall),
                  for (final package in rows) _PackageRow(package: package, access: access),
                ],
              ),
            ),
            if (access.canWrite)
              Align(
                alignment: AlignmentDirectional.centerEnd,
                child: TextButton.icon(
                  key: Key('build-${course.id}'),
                  icon: const Icon(Icons.auto_awesome),
                  label: Text(l.academyUser_buildPackage),
                  onPressed: () => showModalBottomSheet<void>(
                    context: context,
                    isScrollControlled: true,
                    showDragHandle: true,
                    builder: (_) => _PackageSheet(course: course),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _PackageRow extends ConsumerWidget {
  const _PackageRow({required this.package, required this.access});

  final AcademyPackage package;
  final AcademyAccess access;

  Future<void> _run(BuildContext context, WidgetRef ref, Future<void> Function() action, String done, String failed) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await action();
      messenger.showSnackBar(SnackBar(content: Text(done)));
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(describeAccountError(l, error, failed))));
    }
    ref.invalidate(academyPackagesProvider(package.courseId));
  }

  Future<void> _review(BuildContext context, WidgetRef ref, {required bool approved}) async {
    final l = AppLocalizations.of(context);
    final notes = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(approved ? l.academyUser_approve : l.academyUser_reject),
        content: TextField(
          key: const Key('review-notes'),
          controller: notes,
          maxLength: 4000,
          decoration: InputDecoration(labelText: approved ? l.academyUser_approvePrompt : l.academyUser_rejectPrompt),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(l.projects_cancel)),
          FilledButton(
            key: const Key('review-confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: Text(approved ? l.academyUser_approve : l.academyUser_reject),
          ),
        ],
      ),
    );
    final text = notes.text;
    notes.dispose();
    if (ok != true || !context.mounted) return;
    await _run(
      context,
      ref,
      () => ref.read(academyRepositoryProvider).review(package.id, approved: approved, notes: text),
      approved ? l.academyUser_approved : l.academyUser_rejected,
      l.academyUser_reviewError,
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Padding(
      key: Key('package-${package.id}'),
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Expanded(
              child: Text(
                '${l.academyUser_packageVersion(package.version)} · ${l.academyUser_lessons(package.lessonCount)}',
                style: theme.textTheme.bodyMedium,
              ),
            ),
            StatusChip(
              label: package.status,
              positive: package.status == 'approved',
              negative: package.status == 'failed' || package.status == 'rejected',
            ),
          ]),
          if (package.isActive) ...[
            const SizedBox(height: 6),
            const LinearProgressIndicator(),
            const SizedBox(height: 4),
            Text(l.academyUser_building, style: theme.textTheme.bodySmall),
          ],
          if (package.errorCode != null && package.errorCode!.isNotEmpty)
            Text(package.errorCode!, style: TextStyle(color: theme.colorScheme.error)),
          if (package.archiveSha256 != null)
            Text('SHA-256 ${package.archiveSha256!.substring(0, 12)}…', style: theme.textTheme.bodySmall),
          Wrap(spacing: 4, children: [
            if (package.awaitsReview && access.canAssess) ...[
              TextButton(
                key: Key('approve-${package.id}'),
                onPressed: () => _review(context, ref, approved: true),
                child: Text(l.academyUser_approve),
              ),
              TextButton(
                key: Key('reject-${package.id}'),
                onPressed: () => _review(context, ref, approved: false),
                child: Text(l.academyUser_reject),
              ),
            ],
            if (package.downloadReady)
              TextButton.icon(
                key: Key('download-package-${package.id}'),
                icon: const Icon(Icons.download),
                label: Text(l.academyUser_download),
                onPressed: () => _run(context, ref, () async {
                  final file = await ref.read(academyRepositoryProvider).download(package);
                  await ref.read(fileSharerProvider)(file);
                }, l.academyUser_downloadStarted, l.academyUser_downloadError),
              ),
          ]),
        ],
      ),
    );
  }
}

class _CourseSheet extends ConsumerStatefulWidget {
  const _CourseSheet();

  @override
  ConsumerState<_CourseSheet> createState() => _CourseSheetState();
}

class _CourseSheetState extends ConsumerState<_CourseSheet> {
  final _formKey = GlobalKey<FormState>();
  final _code = TextEditingController();
  final _title = TextEditingController();
  final _description = TextEditingController();
  final _competencies = TextEditingController();
  final _passing = TextEditingController(text: '80');
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_code, _title, _description, _competencies, _passing]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _create() async {
    final l = AppLocalizations.of(context);
    if (_busy || !(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final course = await ref.read(academyRepositoryProvider).createCourse(
            code: _code.text,
            title: _title.text,
            description: _description.text,
            competencies: [
              for (final part in _competencies.text.split(',')) if (part.trim().isNotEmpty) part.trim(),
            ],
            passingScore: double.parse(_passing.text.trim()),
          );
      ref.invalidate(academyCoursesProvider);
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.academyUser_courseCreated(course.title))));
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(l, error, l.academyUser_courseCreateError));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.viewInsetsOf(context).bottom + 20),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(l.academyUser_createCourse, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 14),
              TextFormField(
                key: const Key('course-code'),
                controller: _code,
                enabled: !_busy,
                maxLength: 120,
                decoration: InputDecoration(labelText: l.academyUser_code),
                validator: (v) => (v?.trim().length ?? 0) >= 2 ? null : l.academyUser_code,
              ),
              TextFormField(
                key: const Key('course-title'),
                controller: _title,
                enabled: !_busy,
                maxLength: 240,
                decoration: InputDecoration(labelText: l.academyUser_courseTitle),
                validator: (v) => (v?.trim().length ?? 0) >= 2 ? null : l.academyUser_courseTitle,
              ),
              TextFormField(
                controller: _description,
                enabled: !_busy,
                minLines: 2,
                maxLines: 6,
                maxLength: 20000,
                decoration: InputDecoration(labelText: l.academyUser_courseDescription, alignLabelWithHint: true),
              ),
              TextFormField(
                controller: _competencies,
                enabled: !_busy,
                decoration: InputDecoration(labelText: l.academyUser_competencies),
              ),
              const SizedBox(height: 12),
              TextFormField(
                key: const Key('course-passing'),
                controller: _passing,
                enabled: !_busy,
                keyboardType: TextInputType.number,
                decoration: InputDecoration(labelText: l.academyUser_passingScore),
                validator: (v) {
                  final value = double.tryParse(v?.trim() ?? '');
                  return value != null && value >= 0 && value <= 100 ? null : l.academyUser_passingScore;
                },
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Notice(key: const Key('course-error'), text: _error!, tone: NoticeTone.error),
              ],
              const SizedBox(height: 16),
              FilledButton(
                key: const Key('course-create'),
                onPressed: _busy ? null : _create,
                child: Text(l.academyUser_createCourse),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PackageSheet extends ConsumerStatefulWidget {
  const _PackageSheet({required this.course});

  final AcademyCourse course;

  @override
  ConsumerState<_PackageSheet> createState() => _PackageSheetState();
}

class _PackageSheetState extends ConsumerState<_PackageSheet> {
  final _formKey = GlobalKey<FormState>();
  final _domain = TextEditingController();
  final _audience = TextEditingController();
  int _modules = 2;
  int _lessons = 2;
  // Kept for the life of the sheet, so a retried tap reuses the same package.
  final String _requestId = newRequestId();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _domain.dispose();
    _audience.dispose();
    super.dispose();
  }

  Future<void> _queue() async {
    final l = AppLocalizations.of(context);
    if (_busy || !(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(academyRepositoryProvider).queuePackage(
            widget.course.id,
            idempotencyKey: _requestId,
            domain: _domain.text,
            audience: _audience.text,
            modules: _modules,
            lessonsPerModule: _lessons,
          );
      ref.invalidate(academyPackagesProvider(widget.course.id));
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.academyUser_packageQueued)));
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(l, error, l.academyUser_packageCreateError));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _count(String label, int value, ValueChanged<int> onChanged) => DropdownButtonFormField<int>(
        isExpanded: true,
        initialValue: value,
        decoration: InputDecoration(labelText: label),
        items: [for (var i = 1; i <= 8; i++) DropdownMenuItem(value: i, child: Text('$i'))],
        onChanged: _busy ? null : (v) => onChanged(v ?? value),
      );

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final tooMany = _modules * _lessons > 32;
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.viewInsetsOf(context).bottom + 20),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(l.academyUser_buildPackage, style: Theme.of(context).textTheme.titleLarge),
              Text(widget.course.title, style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 14),
              TextFormField(
                key: const Key('package-domain'),
                controller: _domain,
                enabled: !_busy,
                maxLength: 240,
                decoration: InputDecoration(labelText: l.academyUser_domain),
                validator: (v) => (v?.trim().length ?? 0) >= 2 ? null : l.academyUser_domain,
              ),
              TextFormField(
                key: const Key('package-audience'),
                controller: _audience,
                enabled: !_busy,
                maxLength: 240,
                decoration: InputDecoration(labelText: l.academyUser_audience),
                validator: (v) => (v?.trim().length ?? 0) >= 2 ? null : l.academyUser_audience,
              ),
              Row(children: [
                Expanded(child: _count(l.academyUser_modules, _modules, (v) => setState(() => _modules = v))),
                const SizedBox(width: 12),
                Expanded(child: _count(l.academyUser_lessonsPerModule, _lessons, (v) => setState(() => _lessons = v))),
              ]),
              const SizedBox(height: 10),
              Text(l.academyUser_sixLocalePackage, style: Theme.of(context).textTheme.bodySmall),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Notice(key: const Key('package-error'), text: _error!, tone: NoticeTone.error),
              ],
              const SizedBox(height: 16),
              FilledButton(
                key: const Key('package-queue'),
                onPressed: _busy || tooMany ? null : _queue,
                child: Text(l.academyUser_queuePackage),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
