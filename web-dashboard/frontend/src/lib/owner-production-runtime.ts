import { apiClient } from "@/lib/api-client";

export type ProductionRuntimeStatus = "ready" | "degraded" | "blocked";
export type ProductionRuntimeAction = "validate" | "synchronize" | "prepare";

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

export async function fetchProductionRuntime(
  signal?: AbortSignal,
): Promise<ProductionRuntimeSnapshot> {
  return apiClient.get<ProductionRuntimeSnapshot>("/owner/production-runtime", {
    signal,
  });
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
