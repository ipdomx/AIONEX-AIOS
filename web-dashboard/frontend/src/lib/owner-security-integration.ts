import { apiClient } from "@/lib/api-client";

export type SecurityStatus = "secure" | "warning" | "critical";
export type SecurityAction = "validate" | "acknowledge";

export interface SecurityTarget {
  id: string;
  name: string;
  category: string;
  status: SecurityStatus;
  score: number;
  details: string;
  last_checked_at: string;
}

export interface SecuritySnapshot {
  generated_at: string;
  completion: number;
  targets: SecurityTarget[];
}

export async function fetchOwnerSecurityIntegration(
  signal?: AbortSignal,
): Promise<SecuritySnapshot> {
  return apiClient.get<SecuritySnapshot>("/owner/security-integration", {
    signal,
  });
}

export async function runOwnerSecurityCommand(
  targetId: string,
  action: SecurityAction,
): Promise<SecuritySnapshot> {
  return apiClient.post<SecuritySnapshot>(
    `/owner/security-integration/${encodeURIComponent(targetId)}/command`,
    { action },
  );
}
