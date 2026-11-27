import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../widgets/async_view.dart';
import '../../widgets/error_text.dart';
import '../../widgets/notice.dart';
import '../workspace/workspace_models.dart';
import '../workspace/workspace_repository.dart';
import 'studio_hub.dart';

/// The website's preset grid: a family, the capability that gates it, and where it leads.
typedef StudioPreset = ({String key, String capability, String? department, String style});

const studioPresets = <StudioPreset>[
  (key: 'software', capability: 'software', department: 'code', style: 'production software'),
  (key: 'prompts', capability: 'prompt-text', department: 'text', style: 'structured prompt system'),
  (key: 'design', capability: 'design-image', department: 'ui-ux', style: 'accessible product design'),
  (key: 'image', capability: 'design-image', department: 'image', style: 'production visual design'),
  (key: 'audio', capability: 'audio', department: 'audio', style: 'clean production audio'),
  (key: 'video', capability: 'video-motion', department: 'video', style: 'cinematic production video'),
  (key: 'music', capability: 'music-song', department: null, style: 'music production package'),
  (key: 'threeD', capability: 'three-d-xr', department: 'three-d', style: 'interactive 3D/XR'),
  (key: 'courses', capability: 'courses', department: null, style: 'structured learning package'),
  (key: 'sector', capability: 'sector-solutions', department: null, style: 'sector solution blueprint'),
];

String presetLabel(AppLocalizations l, String key) => switch (key) {
      'software' => l.studio_families_software,
      'prompts' => l.studio_families_prompts,
      'design' => l.studio_families_design,
      'image' => l.studio_families_image,
      'audio' => l.studio_families_audio,
      'video' => l.studio_families_video,
      'music' => l.studio_families_music,
      'threeD' => l.studio_families_threeD,
      'courses' => l.studio_families_courses,
      _ => l.studio_families_sector,
    };

String capabilityUnavailable(AppLocalizations l, String? reason) => switch (reason) {
      'external_activation_required' => l.studio_availability_externalActivation,
      'plan_not_supported' || 'plan_not_eligible' => l.studio_availability_plan,
      'permission_required' => l.studio_availability_permission,
      _ => l.studio_availability_owner,
    };

/// Readiness summary and the preset grid. [onPreset] opens a Studio request for that department and style.
class StudioStartTab extends ConsumerWidget {
  const StudioStartTab({super.key, required this.onPreset, required this.onSectors});

  final void Function(String department, String style) onPreset;
  final VoidCallback onSectors;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return AsyncView(
      value: ref.watch(studioHubProvider),
      onRetry: () => ref.invalidate(studioHubProvider),
      builder: (hub) => ListView(
        key: const Key('studio-start'),
        padding: const EdgeInsets.all(16),
        children: [
          Text(l.studio_readinessTitle, style: theme.textTheme.titleMedium),
          Text(l.studio_readinessCopy, style: theme.textTheme.bodySmall),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            Chip(
              key: const Key('studio-ready-count'),
              avatar: const Icon(Icons.verified_outlined, size: 18),
              label: Text('${hub.availableCount} · ${l.studio_readinessAvailable}'),
            ),
            Chip(
              avatar: const Icon(Icons.hourglass_empty, size: 18),
              label: Text('${hub.externalCount} · ${l.studio_readinessExternal}'),
            ),
            Chip(label: Text('${hub.gateCount} ${l.studio_readinessGates}')),
          ]),
          const SizedBox(height: 16),
          Text(l.studio_templatesTitle, style: theme.textTheme.titleMedium),
          Text(l.studio_templatesCopy, style: theme.textTheme.bodySmall),
          const SizedBox(height: 8),
          GridView.count(
            crossAxisCount: 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: 8,
            crossAxisSpacing: 8,
            childAspectRatio: 2.2,
            children: [
              for (final preset in studioPresets)
                _PresetTile(
                  preset: preset,
                  capability: hub.capability(preset.capability),
                  onTap: () {
                    final capability = hub.capability(preset.capability);
                    if (capability?.launchSurface == 'academy' || preset.key == 'courses') {
                      context.go('/academy');
                    } else if (capability?.launchSurface == 'studio-sectors' || preset.key == 'sector') {
                      onSectors();
                    } else if (preset.department == null) {
                      context.go('/projects');
                    } else {
                      onPreset(preset.department!, preset.style);
                    }
                  },
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PresetTile extends StatelessWidget {
  const _PresetTile({required this.preset, required this.capability, required this.onTap});

  final StudioPreset preset;
  final StudioCapability? capability;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final available = capability?.available ?? true;
    final gates = capability?.externalGates.length ?? 0;
    return Tooltip(
      message: available ? (capability?.externalGates.join(' · ') ?? '') : capabilityUnavailable(l, capability?.reason),
      child: Card(
        key: Key('studio-preset-${preset.key}'),
        margin: EdgeInsets.zero,
        child: InkWell(
          onTap: available ? onTap : null,
          borderRadius: BorderRadius.circular(12),
          child: Opacity(
            opacity: available ? 1 : 0.45,
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(presetLabel(l, preset.key), style: theme.textTheme.titleSmall, overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 2),
                  Text(
                    available
                        ? l.studio_readyBadge
                        : capability?.reason == 'external_activation_required'
                            ? l.studio_externalGateBadge
                            : capabilityUnavailable(l, capability?.reason),
                    style: theme.textTheme.labelSmall,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  if (gates > 0)
                    Text('$gates ${l.studio_readinessGates}', style: theme.textTheme.labelSmall),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

final _sectorWorkspacesProvider =
    FutureProvider.autoDispose<List<Workspace>>((ref) => ref.watch(workspaceRepositoryProvider).workspaces());

/// Sector packs turned into projects, plus a custom lawful sector (the website's launchpad).
class StudioSectorsTab extends ConsumerStatefulWidget {
  const StudioSectorsTab({super.key});

  @override
  ConsumerState<StudioSectorsTab> createState() => _StudioSectorsTabState();
}

class _StudioSectorsTabState extends ConsumerState<StudioSectorsTab> {
  final _name = TextEditingController();
  final _audience = TextEditingController();
  final _objective = TextEditingController();
  String? _workspaceId;
  String? _busy;

  @override
  void dispose() {
    _name.dispose();
    _audience.dispose();
    _objective.dispose();
    super.dispose();
  }

  Future<void> _create(String key, {required String name, required String description, required String tag}) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final workspace = _workspaceId;
    if (workspace == null) {
      messenger.showSnackBar(SnackBar(content: Text(l.studio_sectorWorkspaceRequired)));
      return;
    }
    setState(() => _busy = key);
    try {
      final project = await ref.read(workspaceRepositoryProvider).createProject(
            name: name,
            workspaceId: workspace,
            priority: 'medium',
            description: description,
            tags: ['phase36m', 'domain-blueprint-v3', tag],
          );
      messenger.showSnackBar(SnackBar(content: Text(l.studio_sectorProjectCreated(project.name))));
      if (key == 'custom') {
        _name.clear();
        _audience.clear();
        _objective.clear();
      }
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(describeError(l, error))));
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  String _packDescription(SectorPack p) => [
        'Phase 36M governed sector pack: ${p.title}.',
        'Objective: ${p.objective}',
        'Audience: ${p.audience}',
        'Roles: ${p.roles.join(', ')}',
        'Workflows: ${p.workflows.join(' | ')}',
        if (p.safetyBoundaries.isNotEmpty) 'Safety boundaries: ${p.safetyBoundaries.join(' | ')}',
        if (p.externalGates.isNotEmpty) 'External activation gates: ${p.externalGates.join(' | ')}',
        'Domain Blueprint v3: ${jsonEncode(p.blueprint)}',
      ].join('\n');

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final workspaces = ref.watch(_sectorWorkspacesProvider).value ?? const <Workspace>[];
    _workspaceId ??= workspaces.firstOrNull?.id;
    return AsyncView(
      value: ref.watch(sectorCatalogProvider),
      onRetry: () => ref.invalidate(sectorCatalogProvider),
      builder: (catalog) {
        final open = catalog.capability.available && workspaces.isNotEmpty;
        return ListView(
          key: const Key('studio-sectors'),
          padding: const EdgeInsets.all(16),
          children: [
            Text(l.studio_sectorTitle, style: theme.textTheme.titleMedium),
            Text(l.studio_sectorCopy, style: theme.textTheme.bodySmall),
            if (!catalog.capability.available) ...[
              const SizedBox(height: 8),
              Notice(key: const Key('sector-unavailable'), text: capabilityUnavailable(l, catalog.capability.reason)),
            ],
            const SizedBox(height: 8),
            workspaces.isEmpty
                ? Text(l.studio_sectorNoWorkspace, style: theme.textTheme.bodySmall)
                : DropdownButtonFormField<String>(
                    key: const Key('sector-workspace'),
                    initialValue: _workspaceId,
                    isExpanded: true,
                    decoration: InputDecoration(labelText: l.studio_sectorWorkspace),
                    items: [for (final w in workspaces) DropdownMenuItem(value: w.id, child: Text(w.name))],
                    onChanged: (v) => setState(() => _workspaceId = v),
                  ),
            const SizedBox(height: 12),
            for (final p in catalog.packs)
              Card(
                key: Key('sector-${p.key}'),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(p.title, style: theme.textTheme.titleSmall),
                    Text(p.objective, style: theme.textTheme.bodySmall),
                    const SizedBox(height: 6),
                    Wrap(spacing: 6, runSpacing: 6, children: [
                      Chip(visualDensity: VisualDensity.compact, label: Text('${p.entityCount} ${l.studio_sectorEntities}')),
                      Chip(visualDensity: VisualDensity.compact, label: Text('${p.workflowCount} ${l.studio_sectorWorkflows}')),
                      if (p.externalGates.isNotEmpty)
                        Chip(
                          visualDensity: VisualDensity.compact,
                          label: Text('${p.externalGates.length} ${l.studio_sectorGates}'),
                        ),
                    ]),
                    if (p.workflows.isNotEmpty) Text(p.workflows.take(3).join(' · '), style: theme.textTheme.bodySmall),
                    Align(
                      alignment: AlignmentDirectional.centerEnd,
                      child: TextButton.icon(
                        key: Key('sector-use-${p.key}'),
                        icon: const Icon(Icons.create_new_folder_outlined),
                        label: Text(l.studio_sectorUseProject),
                        onPressed: !open || _busy != null
                            ? null
                            : () => _create(p.key, name: p.title, description: _packDescription(p), tag: 'sector:${p.key}'),
                      ),
                    ),
                  ]),
                ),
              ),
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Text(l.studio_customSectorTitle, style: theme.textTheme.titleSmall),
                  Text(l.studio_customSectorCopy, style: theme.textTheme.bodySmall),
                  const SizedBox(height: 8),
                  TextField(
                    key: const Key('sector-custom-name'),
                    controller: _name,
                    inputFormatters: [LengthLimitingTextInputFormatter(160)],
                    decoration: InputDecoration(labelText: l.studio_customSectorName),
                  ),
                  TextField(
                    key: const Key('sector-custom-audience'),
                    controller: _audience,
                    inputFormatters: [LengthLimitingTextInputFormatter(240)],
                    decoration: InputDecoration(labelText: l.studio_customSectorAudience),
                  ),
                  TextField(
                    key: const Key('sector-custom-objective'),
                    controller: _objective,
                    minLines: 2,
                    maxLines: 4,
                    inputFormatters: [LengthLimitingTextInputFormatter(1000)],
                    decoration: InputDecoration(labelText: l.studio_customSectorObjective),
                  ),
                  const SizedBox(height: 8),
                  FilledButton.icon(
                    key: const Key('sector-custom-create'),
                    icon: const Icon(Icons.auto_awesome),
                    label: Text(l.studio_customSectorCreate),
                    onPressed: !open || _busy != null
                        ? null
                        : () {
                            final name = _name.text.trim();
                            final audience = _audience.text.trim();
                            final objective = _objective.text.trim();
                            // Same minimum lengths as the website's form.
                            if (name.length < 2 || audience.length < 2 || objective.length < 10) {
                              ScaffoldMessenger.of(context)
                                  .showSnackBar(SnackBar(content: Text(l.studio_sectorProjectError)));
                              return;
                            }
                            _create(
                              'custom',
                              name: name,
                              tag: 'sector:custom',
                              description: [
                                'Phase 36M custom lawful sector request using the governed Domain Blueprint v3 composer.',
                                'Objective: $objective',
                                'Audience: $audience',
                                'Required: infer bounded roles, entities and workflows; retain human/external authority gates; '
                                    'do not create a sector-specific code fork.',
                              ].join('\n'),
                            );
                          },
                  ),
                ]),
              ),
            ),
          ],
        );
      },
    );
  }
}
