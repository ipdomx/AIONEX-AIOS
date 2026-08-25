import { apiClient } from "@/lib/api-client";

export type OwnerStudioPolicy = {
  enabled: boolean;
  eligible_plans: string[];
  daily_job_limit: number;
  max_concurrent_jobs: number;
  max_attempts: number;
  max_cost_usd: number;
  provider_mode: "provider_neutral";
  moderation_mode: "standard" | "strict";
  version: number;
};

export type OwnerStudioCapability = {
  capability_id: string;
  title: string;
  category: string;
  launch_surface: string;
  departments: string[];
  phase36_capability_ids: string[];
  maturities: string[];
  external_gates: string[];
  policy: OwnerStudioPolicy;
  policy_source: "default" | "owner";
};

export type OwnerStudioSnapshot = {
  provider_activation: string;
  capabilities: OwnerStudioCapability[];
};

export type OwnerStudioPolicyUpdate = Omit<OwnerStudioPolicy, "version">;

export function fetchOwnerStudioGovernance(signal?: AbortSignal) {
  return apiClient.get<OwnerStudioSnapshot>("/owner/studio-governance", {
    signal,
  });
}

export function updateOwnerStudioCapability(
  capabilityId: string,
  policy: OwnerStudioPolicyUpdate,
) {
  return apiClient.patch<{
    capability_id: string;
    policy: OwnerStudioPolicy;
    policy_source: "owner";
  }>(`/owner/studio-governance/${encodeURIComponent(capabilityId)}`, policy);
}
