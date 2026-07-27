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

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function parseSnapshot(response: Response): Promise<OperationsSnapshot> {
  if (!response.ok) throw new Error(`Owner operations request failed: ${response.status}`);
  return response.json() as Promise<OperationsSnapshot>;
}

export async function fetchOwnerOperationsIntegration(signal?: AbortSignal): Promise<OperationsSnapshot> {
  return parseSnapshot(await fetch(`${API_BASE}/owner/operations-integration`, { signal, cache: "no-store" }));
}

export async function runOwnerOperationsCommand(targetId: string, action: OperationsAction): Promise<OperationsSnapshot> {
  return parseSnapshot(await fetch(`${API_BASE}/owner/operations-integration/${encodeURIComponent(targetId)}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  }));
}
