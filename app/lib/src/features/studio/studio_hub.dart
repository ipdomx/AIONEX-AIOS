import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

String _s(Object? v, [String f = '']) => v is String ? v : f;
int _i(Object? v) => v is num ? v.toInt() : 0;
List<String> _strings(Object? v) => v is List ? v.whereType<String>().toList() : const [];
Map<String, Object?> _map(Object? v) => v is Map ? v.cast<String, Object?>() : const {};

/// One governed Studio capability and whether this account can open it now.
@immutable
class StudioCapability {
  const StudioCapability({
    required this.id,
    required this.title,
    required this.launchSurface,
    required this.departments,
    required this.externalGates,
    required this.available,
    required this.reason,
  });

  final String id;
  final String title;
  final String launchSurface;
  final List<String> departments;
  final List<String> externalGates;
  final bool available;
  final String reason;

  factory StudioCapability.fromJson(Map<String, Object?> j) => StudioCapability(
        id: _s(j['capability_id']),
        title: _s(j['title']),
        launchSurface: _s(j['launch_surface']),
        departments: _strings(j['departments']),
        externalGates: _strings(j['external_gates']),
        available: j['available'] == true,
        reason: _s(j['availability_reason']),
      );
}

@immutable
class StudioHub {
  const StudioHub(this.capabilities);
  final List<StudioCapability> capabilities;

  StudioCapability? capability(String id) => capabilities.where((c) => c.id == id).firstOrNull;

  /// False for a department whose capability this account cannot use (unknown departments stay allowed).
  bool departmentAllowed(String department) {
    for (final c in capabilities) {
      if (c.departments.contains(department)) return c.available;
    }
    return true;
  }

  int get availableCount => capabilities.where((c) => c.available).length;
  int get externalCount => capabilities.where((c) => c.reason == 'external_activation_required').length;
  int get gateCount => {for (final c in capabilities) ...c.externalGates}.length;

  factory StudioHub.fromJson(Map<String, Object?> j) => StudioHub([
        for (final r in (j['capabilities'] is List ? j['capabilities']! as List : const []))
          if (r is Map) StudioCapability.fromJson(r.cast<String, Object?>()),
      ]);
}

/// A verified sector specification (Domain Blueprint v3) that starts a project.
@immutable
class SectorPack {
  const SectorPack({
    required this.key,
    required this.title,
    required this.objective,
    required this.audience,
    required this.roles,
    required this.entityCount,
    required this.workflowCount,
    required this.workflows,
    required this.safetyBoundaries,
    required this.externalGates,
    required this.blueprint,
  });

  final String key;
  final String title;
  final String objective;
  final String audience;
  final List<String> roles;
  final int entityCount;
  final int workflowCount;
  final List<String> workflows;
  final List<String> safetyBoundaries;
  final List<String> externalGates;
  final Map<String, Object?> blueprint;

  factory SectorPack.fromJson(Map<String, Object?> j) => SectorPack(
        key: _s(j['key']),
        title: _s(j['title']),
        objective: _s(j['objective']),
        audience: _s(j['audience']),
        roles: _strings(j['roles']),
        entityCount: _i(j['entity_count']),
        workflowCount: _i(j['workflow_count']),
        workflows: _strings(j['workflows']),
        safetyBoundaries: _strings(j['safety_boundaries']),
        externalGates: _strings(j['external_gates']),
        blueprint: _map(j['domain_blueprint']),
      );
}

@immutable
class SectorCatalog {
  const SectorCatalog({required this.capability, required this.packs});
  final StudioCapability capability;
  final List<SectorPack> packs;

  factory SectorCatalog.fromJson(Map<String, Object?> j) => SectorCatalog(
        capability: StudioCapability.fromJson(_map(j['capability'])),
        packs: [
          for (final r in (j['packs'] is List ? j['packs']! as List : const []))
            if (r is Map) SectorPack.fromJson(r.cast<String, Object?>()),
        ],
      );
}

final studioHubProvider = FutureProvider.autoDispose<StudioHub>(
  (ref) async => StudioHub.fromJson(await ref.watch(apiClientProvider).getJson('/studio/hub')),
);

final sectorCatalogProvider = FutureProvider.autoDispose<SectorCatalog>(
  (ref) async => SectorCatalog.fromJson(await ref.watch(apiClientProvider).getJson('/studio/sector-packs')),
);
