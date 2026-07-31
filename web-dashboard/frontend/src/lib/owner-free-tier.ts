import { apiClient } from "@/lib/api-client";

export type OwnerFreeTierPolicy = {
  enabled: boolean;
  project_limit: number;
  monthly_user_message_limit: number;
  monthly_assistant_response_limit: number;
  storage_limit_bytes: number;
  max_message_characters: number;
  registrations_per_ip_per_day: number;
  minimum_age: number;
  require_phone_verification: boolean;
  require_device_signals: boolean;
  one_account_per_network: boolean;
  one_account_per_device: boolean;
  telemetry_retention_days: number;
  consent_version: string;
  require_country: boolean;
  require_cookie_consent: boolean;
};

export type OwnerFreeAccount = {
  id: string;
  name: string;
  email: string;
  status: string;
  created_at: string;
  quota: Record<string, unknown>;
  registration: Record<string, unknown> | null;
};

export type OwnerFreeTierSnapshot = {
  policy: OwnerFreeTierPolicy;
  accounts: OwnerFreeAccount[];
  account_count: number;
};

export function fetchOwnerFreeTier(
  signal?: AbortSignal,
): Promise<OwnerFreeTierSnapshot> {
  return apiClient.get<OwnerFreeTierSnapshot>("/owner/free-tier", { signal });
}

export function updateOwnerFreeTier(
  updates: Partial<OwnerFreeTierPolicy>,
): Promise<OwnerFreeTierSnapshot> {
  return apiClient.patch<OwnerFreeTierSnapshot>("/owner/free-tier", updates);
}
