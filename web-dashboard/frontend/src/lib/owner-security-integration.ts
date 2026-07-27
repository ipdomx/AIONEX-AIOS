export type SecurityStatus = "secure" | "warning" | "critical";
export type SecurityAction = "validate" | "rotate" | "quarantine";

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

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchOwnerSecurityIntegration(signal?: AbortSignal): Promise<SecuritySnapshot> {
  const response = await fetch(`${API_BASE}/owner/security-integration`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Security integration request failed: ${response.status}`);
  return response.json() as Promise<SecuritySnapshot>;
}

export async function runOwnerSecurityCommand(targetId: string, action: SecurityAction): Promise<SecuritySnapshot> {
  const response = await fetch(`${API_BASE}/owner/security-integration/${encodeURIComponent(targetId)}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!response.ok) throw new Error(`Security command failed: ${response.status}`);
  return response.json() as Promise<SecuritySnapshot>;
}
