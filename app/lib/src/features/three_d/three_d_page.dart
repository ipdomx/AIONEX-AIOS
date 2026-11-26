import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/api/api_exception.dart';
import '../../core/files/file_share.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../workspace/workspace_models.dart';
import 'three_d_repository.dart';

/// Picks the source image; replaced in tests.
typedef SourceImagePicker = Future<({Uint8List bytes, String name})?> Function();

final sourceImagePickerProvider = Provider<SourceImagePicker>((ref) => () async {
      final file = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 2048, maxHeight: 2048, imageQuality: 92);
      if (file == null) return null;
      return (bytes: await file.readAsBytes(), name: file.name);
    });

String describeThreeDError(AppLocalizations l, Object error, String fallback) {
  if (error is! ApiException) return fallback;
  switch (error.code) {
    case 'THREE_D_MONTHLY_QUOTA_REACHED':
      return l.threeDStudio_errors_quota;
    case 'THREE_D_CONCURRENCY_LIMIT':
      return l.threeDStudio_errors_concurrency;
    case 'THREE_D_ACCESS_NOT_GRANTED':
      return l.threeDStudio_errors_notGranted;
    case 'THREE_D_PROVIDERS_UNAVAILABLE' || 'THREE_D_PROVIDER_CIRCUIT_OPEN' || 'THREE_D_PROVIDER_PAUSED' || 'THREE_D_PROVIDER_AUTH':
      return l.threeDStudio_errors_providerUnavailable;
    case 'MEDIA_MAINTENANCE_CLOSED' || 'MEDIA_MAINTENANCE_UNAVAILABLE':
      return l.threeDStudio_errors_maintenance;
    case 'THREE_D_HUNYUAN_OUTPUT_TERRITORY_BLOCKED' || 'THREE_D_PROVIDER_NOT_PERMITTED':
      return l.threeDStudio_errors_jurisdiction;
    case 'THREE_D_IDEMPOTENCY_CONFLICT':
      return l.threeDStudio_errors_duplicate;
  }
  return switch (error.statusCode) {
    401 => l.threeDStudio_errors_sessionExpired,
    403 => l.threeDStudio_errors_forbidden,
    410 => l.threeDStudio_errors_expired,
    413 => l.threeDStudio_errors_tooLarge,
    429 => l.threeDStudio_errors_rateLimited,
    451 => l.threeDStudio_errors_jurisdiction,
    503 => l.threeDStudio_errors_providerUnavailable,
    _ => fallback,
  };
}

String threeDStatusLabel(AppLocalizations l, String status) => switch (status) {
      'queued' => l.threeDStudio_status_queued,
      'running' => l.threeDStudio_status_running,
      'cancel_requested' => l.threeDStudio_status_cancel_requested,
      'needs_clarification' => l.threeDStudio_status_needs_clarification,
      'completed' => l.threeDStudio_status_completed,
      'failed' => l.threeDStudio_status_failed,
      'cancelled' => l.threeDStudio_status_cancelled,
      _ => status,
    };

/// Image to 3D for one project: access and quota, new job, live list, links.
class ThreeDPage extends ConsumerStatefulWidget {
  const ThreeDPage({super.key, required this.projectId, this.pollInterval = const Duration(seconds: 4)});

  final String projectId;
  final Duration pollInterval;

  @override
  ConsumerState<ThreeDPage> createState() => _ThreeDPageState();
}

class _ThreeDPageState extends ConsumerState<ThreeDPage> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(widget.pollInterval, (_) {
      final jobs = ref.read(threeDJobsProvider(widget.projectId)).value;
      if (jobs != null && jobs.any((j) => j.isActive)) {
        ref.invalidate(threeDJobsProvider(widget.projectId));
        ref.invalidate(threeDAccessProvider(widget.projectId));
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _refresh() {
    ref.invalidate(threeDAccessProvider(widget.projectId));
    ref.invalidate(threeDJobsProvider(widget.projectId));
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final access = ref.watch(threeDAccessProvider(widget.projectId));
    return Scaffold(
      appBar: AppBar(
        title: Text(l.threeDStudio_title),
        actions: [IconButton(tooltip: l.threeDStudio_refresh, icon: const Icon(Icons.refresh), onPressed: _refresh)],
      ),
      body: RefreshIndicator(
        onRefresh: () async => _refresh(),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 40),
          children: [
            Text(l.threeDStudio_description, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            access.when(
              loading: () => const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator())),
              error: (error, _) => Notice(
                key: const Key('three-d-access-error'),
                text: describeThreeDError(l, error, l.threeDStudio_errors_load),
                tone: NoticeTone.error,
              ),
              data: (value) => _AccessCard(projectId: widget.projectId, access: value),
            ),
            const SizedBox(height: 16),
            Text(l.threeDStudio_jobs_title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            AsyncView(
              value: ref.watch(threeDJobsProvider(widget.projectId)),
              onRetry: () => ref.invalidate(threeDJobsProvider(widget.projectId)),
              builder: (jobs) => jobs.isEmpty
                  ? Text(l.threeDStudio_jobs_empty, style: Theme.of(context).textTheme.bodySmall)
                  : Column(children: [
                      for (final job in jobs) _JobCard(projectId: widget.projectId, job: job, access: access.value),
                    ]),
            ),
          ],
        ),
      ),
    );
  }
}

class _AccessCard extends ConsumerStatefulWidget {
  const _AccessCard({required this.projectId, required this.access});

  final String projectId;
  final ThreeDAccess access;

  @override
  ConsumerState<_AccessCard> createState() => _AccessCardState();
}

class _AccessCardState extends ConsumerState<_AccessCard> {
  ({Uint8List bytes, String name, String type})? _image;
  bool _terms = false;
  bool _busy = false;
  String? _error;
  // One key per chosen image, so a retried tap never queues (and bills) twice.
  String _requestId = newRequestId();

  Future<void> _pick() async {
    final l = AppLocalizations.of(context);
    final picked = await ref.read(sourceImagePickerProvider)();
    if (picked == null || !mounted) return;
    final type = sourceImageType(picked.bytes);
    setState(() {
      _error = null;
      _image = null;
      if (type == null) {
        _error = l.threeDStudio_errors_invalidType;
      } else if (picked.bytes.length > widget.access.maxInputMegabytes * 1024 * 1024) {
        _error = l.threeDStudio_errors_tooLargeLimit(widget.access.maxInputMegabytes);
      } else {
        _image = (bytes: picked.bytes, name: picked.name, type: type);
        _requestId = newRequestId();
      }
    });
  }

  Future<void> _submit() async {
    final l = AppLocalizations.of(context);
    final image = _image;
    if (_busy || image == null) return;
    if (widget.access.termsRequired && !_terms) {
      setState(() => _error = l.threeDStudio_errors_termsRequired);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(threeDRepositoryProvider).create(
            widget.projectId,
            image: image.bytes,
            filename: image.name,
            mediaType: image.type,
            termsVersion: widget.access.termsVersion,
            termsAccepted: _terms,
            idempotencyKey: _requestId,
          );
      if (!mounted) return;
      setState(() => _image = null);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.threeDStudio_queued)));
      ref.invalidate(threeDJobsProvider(widget.projectId));
      ref.invalidate(threeDAccessProvider(widget.projectId));
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeThreeDError(l, error, l.threeDStudio_errors_create));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final access = widget.access;
    if (!access.serviceEnabled) {
      return EmptyState(icon: Icons.pause_circle_outline, title: l.threeDStudio_unavailable_disabledTitle, message: l.threeDStudio_unavailable_disabledBody);
    }
    if (!access.eligible) {
      return EmptyState(icon: Icons.view_in_ar_outlined, title: l.threeDStudio_upgrade_planTitle, message: l.threeDStudio_upgrade_planBody);
    }
    if (access.monthlyRemaining <= 0) {
      return EmptyState(icon: Icons.hourglass_empty, title: l.threeDStudio_upgrade_quotaTitle, message: l.threeDStudio_upgrade_quotaBody);
    }
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Wrap(spacing: 8, runSpacing: 8, children: [
              Chip(label: Text('${l.threeDStudio_quota_plan}: ${access.planCode}')),
              Chip(label: Text('${l.threeDStudio_quota_remaining}: ${access.monthlyRemaining}/${access.monthlyQuota}')),
              Chip(label: Text('${l.threeDStudio_quota_active}: ${access.activeJobs}/${access.maxConcurrentJobs}')),
            ]),
            const SizedBox(height: 10),
            Text(l.threeDStudio_create_title, style: theme.textTheme.titleMedium),
            Text(l.threeDStudio_create_body, style: theme.textTheme.bodySmall),
            const SizedBox(height: 8),
            Text('${l.threeDStudio_create_costLabel} ${l.threeDStudio_create_costValue}', style: theme.textTheme.bodySmall),
            Text('${l.threeDStudio_create_outputLabel} ${l.threeDStudio_create_outputValue}', style: theme.textTheme.bodySmall),
            Text(l.threeDStudio_create_modelPolicy, style: theme.textTheme.bodySmall),
            if (access.showsHunyuanNotice && access.operator.isNotEmpty)
              Text(l.threeDStudio_create_hunyuanNoAffiliation(access.operator), style: theme.textTheme.bodySmall),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              key: const Key('three-d-pick'),
              onPressed: _busy ? null : _pick,
              icon: const Icon(Icons.image_outlined),
              label: Text(_image == null ? l.threeDStudio_create_imageLabel : l.threeDStudio_create_selected(_image!.name)),
            ),
            Text(l.threeDStudio_create_imageHint(access.maxInputMegabytes), style: theme.textTheme.bodySmall),
            if (_image != null) ...[
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Image.memory(_image!.bytes, height: 140, fit: BoxFit.contain),
              ),
            ],
            if (access.termsRequired)
              CheckboxListTile(
                key: const Key('three-d-terms'),
                contentPadding: EdgeInsets.zero,
                value: _terms,
                onChanged: _busy ? null : (v) => setState(() => _terms = v ?? false),
                title: Text(l.threeDStudio_terms_consent, style: theme.textTheme.bodySmall),
                subtitle: Text(access.termsVersion, style: theme.textTheme.labelSmall),
              ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Notice(key: const Key('three-d-error'), text: _error!, tone: NoticeTone.error),
            ],
            const SizedBox(height: 10),
            FilledButton.icon(
              key: const Key('three-d-submit'),
              onPressed: _busy || _image == null || !access.canCreate ? null : _submit,
              icon: const Icon(Icons.view_in_ar),
              label: Text(_busy ? l.threeDStudio_create_submitting : l.threeDStudio_create_submit),
            ),
            if (access.activeJobs >= access.maxConcurrentJobs)
              Text(l.threeDStudio_errors_concurrency, style: theme.textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}

class _JobCard extends ConsumerStatefulWidget {
  const _JobCard({required this.projectId, required this.job, required this.access});

  final String projectId;
  final ThreeDJob job;
  final ThreeDAccess? access;

  @override
  ConsumerState<_JobCard> createState() => _JobCardState();
}

class _JobCardState extends ConsumerState<_JobCard> {
  ThreeDLinks? _links;
  Uint8List? _preview;
  bool _busy = false;
  bool _terms = false;

  ThreeDRepository get _repo => ref.read(threeDRepositoryProvider);

  Future<void> _guard(Future<void> Function() action, String failed) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      await action();
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(describeThreeDError(l, error, failed))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _loadLinks() => _guard(() async {
        final links = await _repo.links(widget.projectId, widget.job.id);
        Uint8List? preview;
        if (links.previewUrl != null) {
          try {
            preview = Uint8List.fromList((await _repo.download(ThreeDLink(label: 'preview', filename: 'preview.png', url: links.previewUrl!))).bytes);
          } on Object {
            preview = null;
          }
        }
        if (mounted) {
          setState(() {
            _links = links;
            _preview = preview;
          });
        }
      }, AppLocalizations.of(context).threeDStudio_errors_links);

  Future<void> _save(ThreeDLink link) => _guard(() async {
        final file = await _repo.download(link);
        await ref.read(fileSharerProvider)(file);
      }, AppLocalizations.of(context).threeDStudio_errors_links);

  Future<void> _clarify() async {
    final l = AppLocalizations.of(context);
    final access = widget.access;
    if (access == null) return;
    if (access.termsRequired && !_terms) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.threeDStudio_errors_termsRequired)));
      return;
    }
    final picked = await ref.read(sourceImagePickerProvider)();
    if (picked == null || !mounted) return;
    final type = sourceImageType(picked.bytes);
    if (type == null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.threeDStudio_errors_invalidType)));
      return;
    }
    await _guard(() async {
      await _repo.clarify(widget.projectId, widget.job.id,
          image: picked.bytes, filename: picked.name, mediaType: type, termsVersion: access.termsVersion, termsAccepted: _terms);
      ref.invalidate(threeDJobsProvider(widget.projectId));
    }, l.threeDStudio_errors_clarify);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final job = widget.job;
    final links = _links;
    return Card(
      key: Key('three-d-job-${job.id}'),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(children: [
              Expanded(
                child: Text(
                  job.artifactFilename ?? l.threeDStudio_viewer_attempt(job.attempts, job.maxAttempts),
                  style: theme.textTheme.titleSmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              StatusChip(
                label: threeDStatusLabel(l, job.status),
                positive: job.status == 'completed',
                negative: job.status == 'failed',
              ),
            ]),
            Text(
              [l.threeDStudio_viewer_stage(job.stage), l.threeDStudio_jobs_cost(job.estimatedCostUsd.toStringAsFixed(2))].join(' · '),
              style: theme.textTheme.bodySmall,
            ),
            if (job.isActive) ...[
              const SizedBox(height: 8),
              LinearProgressIndicator(value: job.progress > 0 ? job.progress.clamp(0, 100) / 100 : null),
              const SizedBox(height: 4),
              Text(l.threeDStudio_viewer_inProgress, style: theme.textTheme.bodySmall),
            ],
            if (job.errorMessage != null && job.errorMessage!.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(job.errorMessage!, style: TextStyle(color: theme.colorScheme.error)),
              ),
            if (job.status == 'needs_clarification') ...[
              if (widget.access?.termsRequired ?? false)
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _terms,
                  onChanged: _busy ? null : (v) => setState(() => _terms = v ?? false),
                  title: Text(l.threeDStudio_terms_consent, style: theme.textTheme.bodySmall),
                ),
              OutlinedButton.icon(
                key: Key('three-d-clarify-${job.id}'),
                onPressed: _busy ? null : _clarify,
                icon: const Icon(Icons.image_search),
                label: Text(l.threeDStudio_viewer_clarifySubmit),
              ),
            ],
            if (job.status == 'completed' && !job.hasArtifact)
              Text(l.threeDStudio_viewer_noArtifact, style: theme.textTheme.bodySmall),
            if (_preview != null) ...[
              const SizedBox(height: 8),
              ClipRRect(borderRadius: BorderRadius.circular(8), child: Image.memory(_preview!, height: 180, fit: BoxFit.contain)),
            ],
            Wrap(spacing: 4, children: [
              if (job.canCancel)
                TextButton(
                  key: Key('three-d-cancel-${job.id}'),
                  onPressed: _busy
                      ? null
                      : () => _guard(() async {
                            await _repo.cancel(widget.projectId, job.id);
                            ref.invalidate(threeDJobsProvider(widget.projectId));
                          }, l.threeDStudio_errors_cancel),
                  child: Text(l.threeDStudio_viewer_cancel),
                ),
              if (job.status == 'completed' && job.hasArtifact && links == null)
                TextButton.icon(
                  key: Key('three-d-links-${job.id}'),
                  onPressed: _busy ? null : _loadLinks,
                  icon: const Icon(Icons.link),
                  label: Text(l.app_threeDLinks),
                ),
              if (links != null) ...[
                TextButton.icon(
                  key: Key('three-d-glb-${job.id}'),
                  onPressed: _busy ? null : () => _save(links.glb),
                  icon: const Icon(Icons.download),
                  label: Text(l.threeDStudio_download_glb),
                ),
                for (final export in links.exports)
                  TextButton.icon(
                    onPressed: _busy ? null : () => _save(export),
                    icon: const Icon(Icons.download_outlined),
                    label: Text(switch (export.label) {
                      'obj' => l.threeDStudio_download_server_obj,
                      'fbx' => l.threeDStudio_download_server_fbx,
                      'usdz' => l.threeDStudio_download_server_usdz,
                      _ => export.filename,
                    }),
                  ),
                TextButton(onPressed: _busy ? null : _loadLinks, child: Text(l.threeDStudio_download_refresh)),
              ],
            ]),
            if (links != null && widget.access != null)
              Text(l.threeDStudio_download_expiry((widget.access!.signedUrlTtlSeconds / 60).ceil()), style: theme.textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}
