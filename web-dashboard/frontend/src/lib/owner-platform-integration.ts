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

export async function fetchOwnerPlatformIntegration(signal?: AbortSignal): Promise<IntegrationSnapshot> {
  const response = await fetch("/api/owner/platform-integration/snapshot", { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load integration snapshot: ${response.status}`);
  return response.json() as Promise<IntegrationSnapshot>;
}

export async function runOwnerIntegrationCommand(
  targetId: string,
  action: "refresh" | "reconnect" | "validate",
): Promise<IntegrationSnapshot> {
  const response = await fetch("/api/owner/platform-integration/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_id: targetId, action }),
  });
  if (!response.ok) throw new Error(`Integration command failed: ${response.status}`);
  return response.json() as Promise<IntegrationSnapshot>;
}
