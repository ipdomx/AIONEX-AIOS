import { apiClient } from "@/lib/api-client";

export type ProductionRuntimeStatus = "ready" | "degraded" | "blocked";
export type ProductionRuntimeAction = "validate";

export interface ProductionRuntimeTarget {
  id: string;
  name: string;
  category: string;
  status: ProductionRuntimeStatus;
  readiness: number;
  details: string;
  last_checked_at: string;
}

export interface ProductionRuntimeSnapshot {
  generated_at: string;
  completion: number;
  public_origin: string;
  api_origin: string;
  targets: ProductionRuntimeTarget[];
}

export interface ProjectExecutionFabricSnapshot {
  captured_at: string;
  queued: number;
  running: number;
  retry_queued: number;
  dead_lettered: number;
  oldest_queue_wait_seconds: number;
  queue_by_resource_class: Record<string, number>;
  workers_online: number;
  worker_capacity: number;
  worker_active_slots: number;
  worker_saturation: number;
}

export async function fetchProductionRuntime(
  signal?: AbortSignal,
): Promise<ProductionRuntimeSnapshot> {
  return apiClient.get<ProductionRuntimeSnapshot>("/owner/production-runtime", {
    signal,
  });
}

export async function fetchProjectExecutionFabric(
  signal?: AbortSignal,
): Promise<ProjectExecutionFabricSnapshot> {
  return apiClient.get<ProjectExecutionFabricSnapshot>(
    "/owner/production-runtime/project-execution-fabric",
    { signal },
  );
}

export async function runProductionRuntimeCommand(
  targetId: string,
  action: ProductionRuntimeAction,
): Promise<ProductionRuntimeSnapshot> {
  return apiClient.post<ProductionRuntimeSnapshot>(
    "/owner/production-runtime/command",
    {
      target_id: targetId,
      action,
    },
  );
}
