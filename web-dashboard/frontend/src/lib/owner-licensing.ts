export type LicenseRecord = {
  id: string;
  organization: string;
  plan: "enterprise" | "professional" | "starter";
  seats: number;
  activeSeats: number;
  status: "active" | "expiring" | "suspended" | "pending";
  expiresAt: string;
  monthlyValue: number;
};

const fallbackLicenses: LicenseRecord[] = [
  { id: "lic-aionex", organization: "AIONEX", plan: "enterprise", seats: 250, activeSeats: 184, status: "active", expiresAt: "2027-07-01", monthlyValue: 24000 },
  { id: "lic-northstar", organization: "Northstar Labs", plan: "professional", seats: 80, activeSeats: 67, status: "expiring", expiresAt: "2026-08-15", monthlyValue: 6800 },
  { id: "lic-orbit", organization: "Orbit Systems", plan: "starter", seats: 20, activeSeats: 14, status: "pending", expiresAt: "2026-09-01", monthlyValue: 1200 },
];

export async function fetchOwnerLicenses(signal?: AbortSignal): Promise<LicenseRecord[]> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL ?? "/api/owner/licenses";
  try {
    const response = await fetch(endpoint, { headers: { Accept: "application/json" }, cache: "no-store", signal });
    if (!response.ok) throw new Error(`License request failed with ${response.status}`);
    const payload = await response.json();
    return Array.isArray(payload) ? payload : fallbackLicenses;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return fallbackLicenses;
  }
}

export async function updateOwnerLicense(id: string, action: "renew" | "suspend" | "restore", seats?: number): Promise<void> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL ?? "/api/owner/licenses";
  const response = await fetch(`${endpoint}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ action, seats }),
  });
  if (!response.ok) throw new Error(`License update failed with ${response.status}`);
}
