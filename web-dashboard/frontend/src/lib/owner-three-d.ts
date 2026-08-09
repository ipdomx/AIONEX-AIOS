import { apiClient } from "@/lib/api-client";

export type OwnerThreeDPolicy = {
  enabled: boolean;
  allowed_plan_codes: string[];
  required_entitlement: string;
  allowed_user_ids: string[];
  denied_user_ids: string[];
  max_concurrent_jobs_per_user: number;
  max_runtime_seconds: number;
  max_queue_seconds: number;
  max_retries: number;
  max_estimated_job_cost_usd: number;
  daily_spend_limit_usd: number;
  monthly_spend_limit_usd: number;
  owner_alert_threshold_pct: number;
  monthly_jobs_per_user: number;
  max_input_megabytes: number;
  max_texture_size: number;
  artifact_retention_days: number;
  signed_url_ttl_seconds: number;
  compression_policy: "compat" | "meshopt";
};

export type OwnerThreeDSnapshot = { policy: OwnerThreeDPolicy };
export function fetchOwnerThreeD(signal?: AbortSignal) {
  return apiClient.get<OwnerThreeDSnapshot>("/owner/3d", { signal });
}
export function updateOwnerThreeD(updates: Partial<OwnerThreeDPolicy>) {
  return apiClient.patch<OwnerThreeDSnapshot>("/owner/3d", updates);
}
