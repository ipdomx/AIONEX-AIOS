import { apiClient } from "@/lib/api-client";

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

export async function fetchOwnerLicenses(
  signal?: AbortSignal,
): Promise<LicenseRecord[]> {
  return apiClient.get<LicenseRecord[]>("/owner/licenses", { signal });
}

export async function updateOwnerLicense(
  id: string,
  action: "renew" | "suspend" | "restore",
  seats?: number,
): Promise<LicenseRecord> {
  return apiClient.patch<LicenseRecord>(
    `/owner/licenses/${encodeURIComponent(id)}`,
    {
      action,
      seats,
    },
  );
}
