import { apiClient } from "@/lib/api-client";

export type FinalIntegrationStatus = "ready" | "warning" | "blocked";
export type FinalIntegrationAction = "validate" | "synchronize" | "close";

export type FinalIntegrationTarget = {
  id: string;
  name: string;
  category: string;
  status: FinalIntegrationStatus;
  readiness: number;
  details: string;
  last_checked_at: string;
};

export type FinalIntegrationSnapshot = {
  generated_at: string;
  completion: number;
  targets: FinalIntegrationTarget[];
};

export async function fetchFinalPlatformIntegration(
  signal?: AbortSignal,
): Promise<FinalIntegrationSnapshot> {
  return apiClient.get<FinalIntegrationSnapshot>(
    "/owner/final-platform-integration",
    {
      signal,
    },
  );
}

export async function runFinalPlatformIntegrationCommand(
  targetId: string,
  action: FinalIntegrationAction,
): Promise<FinalIntegrationSnapshot> {
  return apiClient.post<FinalIntegrationSnapshot>(
    "/owner/final-platform-integration/command",
    { target_id: targetId, action },
  );
}
