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

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

async function parseResponse(response: Response): Promise<FinalIntegrationSnapshot> {
  if (!response.ok) {
    throw new Error(`Final integration request failed with ${response.status}`);
  }
  return response.json() as Promise<FinalIntegrationSnapshot>;
}

export async function fetchFinalPlatformIntegration(signal?: AbortSignal): Promise<FinalIntegrationSnapshot> {
  const response = await fetch(`${API_BASE}/owner/final-platform-integration`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  return parseResponse(response);
}

export async function runFinalPlatformIntegrationCommand(
  targetId: string,
  action: FinalIntegrationAction,
): Promise<FinalIntegrationSnapshot> {
  const response = await fetch(`${API_BASE}/owner/final-platform-integration/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ target_id: targetId, action }),
  });
  return parseResponse(response);
}
