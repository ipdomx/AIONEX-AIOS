import { apiClient } from "@/lib/api-client";

export type OperationsStatus = "healthy" | "degraded" | "offline";
export type OperationsAction = "validate" | "recover" | "synchronize";

export interface OperationsTarget {
  id: string;
  name: string;
  category: string;
  status: OperationsStatus;
  readiness: number;
  details: string;
  last_checked_at: string;
}

export interface OperationsSnapshot {
  generated_at: string;
  completion: number;
  targets: OperationsTarget[];
}

export async function fetchOwnerOperationsIntegration(
  signal?: AbortSignal,
): Promise<OperationsSnapshot> {
  return apiClient.get<OperationsSnapshot>("/owner/operations-integration", {
    signal,
  });
}

export async function runOwnerOperationsCommand(
  targetId: string,
  action: OperationsAction,
): Promise<OperationsSnapshot> {
  return apiClient.post<OperationsSnapshot>(
    `/owner/operations-integration/${encodeURIComponent(targetId)}/command`,
    { action },
  );
}
