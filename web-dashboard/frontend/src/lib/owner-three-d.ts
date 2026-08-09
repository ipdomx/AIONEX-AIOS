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
  duplicate_window_seconds: number;
  provider_failure_threshold: number;
  provider_circuit_open_seconds: number;
  cleanup_interval_seconds: number;
  cleanup_batch_size: number;
  temporary_input_retention_hours: number;
};

export type OwnerThreeDOperations = {
  circuit: {
    state: string;
    available: boolean;
    consecutive_failures: number;
    open_until: string | null;
    last_failure_at: string | null;
    last_success_at: string | null;
    last_error_code: string | null;
  };
  spend: {
    daily_usd: number;
    monthly_usd: number;
    daily_limit_usd: number;
    monthly_limit_usd: number;
    alert_threshold_pct: number;
  };
  jobs: {
    total: number;
    active: number;
    completed: number;
    failed: number;
    cancelled: number;
    success_rate_pct: number;
    avg_duration_seconds: number;
    avg_gpu_runtime_seconds: number;
    avg_provider_delay_seconds: number;
  };
  cleanup: {
    artifact_retention_days: number;
    temporary_input_retention_hours: number;
    interval_seconds: number;
  };
};

export type OwnerThreeDSnapshot = {
  policy: OwnerThreeDPolicy;
  operations: OwnerThreeDOperations;
  cleanup_result?: { artifacts_expired: number; stale_inputs_cleaned: number };
};
export function fetchOwnerThreeD(signal?: AbortSignal) {
  return apiClient.get<OwnerThreeDSnapshot>("/owner/3d", { signal });
}
export function updateOwnerThreeD(updates: Partial<OwnerThreeDPolicy>) {
  return apiClient.patch<OwnerThreeDSnapshot>("/owner/3d", updates);
}

export function resetOwnerThreeDCircuit() {
  return apiClient.post<OwnerThreeDSnapshot>("/owner/3d/circuit/reset", {});
}
export function cleanupOwnerThreeD() {
  return apiClient.post<OwnerThreeDSnapshot>("/owner/3d/cleanup", {});
}
export function fetchOwnerThreeDMetrics(signal?: AbortSignal) {
  return apiClient.get<string>("/owner/3d/metrics", { signal });
}
