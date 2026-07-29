import { apiClient } from "@/lib/api-client";

export type IntegrationStatus = "connected" | "degraded" | "disconnected";

export interface IntegrationTarget {
  id: string;
  name: string;
  category: string;
  status: IntegrationStatus;
  health: number;
  endpoint: string;
  owner_visible: boolean;
  last_checked_at: string;
  details: string;
}

export interface IntegrationSnapshot {
  generated_at: string;
  completion: number;
  targets: IntegrationTarget[];
}

export async function fetchOwnerPlatformIntegration(
  signal?: AbortSignal,
): Promise<IntegrationSnapshot> {
  return apiClient.get<IntegrationSnapshot>(
    "/owner/platform-integration/snapshot",
    { signal },
  );
}

export async function runOwnerIntegrationCommand(
  targetId: string,
  action: "refresh" | "reconnect" | "validate",
): Promise<IntegrationSnapshot> {
  return apiClient.post<IntegrationSnapshot>(
    "/owner/platform-integration/command",
    {
      target_id: targetId,
      action,
    },
  );
}
