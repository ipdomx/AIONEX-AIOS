const API_ORIGIN = process.env.NEXT_PUBLIC_API_ORIGIN ?? "http://localhost:8000";

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

async function parseSnapshot(response: Response): Promise<ProductionRuntimeSnapshot> {
  if (!response.ok) throw new Error(`Production runtime request failed: ${response.status}`);
  return response.json() as Promise<ProductionRuntimeSnapshot>;
}

export async function fetchProductionRuntime(signal?: AbortSignal): Promise<ProductionRuntimeSnapshot> {
  return parseSnapshot(await fetch(`${API_ORIGIN}/owner/production-runtime`, { signal, cache: "no-store" }));
}

export async function runProductionRuntimeCommand(
  targetId: string,
  action: ProductionRuntimeAction,
): Promise<ProductionRuntimeSnapshot> {
  return parseSnapshot(
    await fetch(`${API_ORIGIN}/owner/production-runtime/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_id: targetId, action }),
    }),
  );
}
