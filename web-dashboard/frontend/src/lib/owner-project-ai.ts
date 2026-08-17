import { apiClient } from "@/lib/api-client";

export type ProjectAIAccessClass = "free" | "paid";

export type ProjectAIAccessPolicy = {
  enabled: boolean;
  access_class: ProjectAIAccessClass;
  allowed_provider_models: string[];
  max_project_cost_usd: number;
  offline_only: boolean;
  privacy_mode: boolean;
  max_fallbacks: number;
};

export type ProjectAIProviderModel = {
  model: string;
  expires_at: string | null;
  local: boolean;
  policy_ref: string | null;
};

export type ProjectAIProvider = {
  id: string;
  type: string;
  status: string;
  enabled: boolean;
  validated_models: ProjectAIProviderModel[];
};

export type ProjectAIManagedUser = {
  id: string;
  name: string;
  email: string;
  organization_id: string;
  organization_name: string;
  plan: string;
  access_class: ProjectAIAccessClass;
  override_active: boolean;
};

export type ProjectAIUserOverride = {
  user_id: string;
  policy: ProjectAIAccessPolicy;
};

export type ProjectAIAccessSnapshot = {
  platform_provider_organization_id: string;
  plan_policies: Record<ProjectAIAccessClass, ProjectAIAccessPolicy>;
  user_overrides: ProjectAIUserOverride[];
  users: ProjectAIManagedUser[];
  providers: ProjectAIProvider[];
};

export type ProjectAIProviderFinance = {
  provider_id: string;
  provider_type: string;
  enabled: boolean;
  funded_usd: number;
  consumed_since_topup_usd: number;
  remaining_usd: number;
  low_balance_threshold_usd: number;
  critical_balance_threshold_usd: number;
  state: "healthy" | "low" | "critical" | "disabled";
  policy_version: number;
};

export type ProjectAIProviderFinanceUpdate = {
  funded_credit_usd: number;
  low_balance_threshold_usd: number;
  critical_balance_threshold_usd: number;
  enabled: boolean;
};

export function fetchProjectAIAccess(
  signal?: AbortSignal,
): Promise<ProjectAIAccessSnapshot> {
  return apiClient.get<ProjectAIAccessSnapshot>("/owner/project-ai/access", {
    signal,
  });
}

export function updateProjectAIPlanPolicy(
  accessClass: ProjectAIAccessClass,
  updates: Partial<ProjectAIAccessPolicy>,
): Promise<{ policy: ProjectAIAccessPolicy }> {
  return apiClient.put<{ policy: ProjectAIAccessPolicy }>(
    `/owner/project-ai/access/plans/${accessClass}`,
    updates,
  );
}

export function updateProjectAIUserPolicy(
  userId: string,
  updates: ProjectAIAccessPolicy,
): Promise<{ user_id: string; policy: ProjectAIAccessPolicy }> {
  return apiClient.put<{ user_id: string; policy: ProjectAIAccessPolicy }>(
    `/owner/project-ai/access/users/${userId}`,
    updates,
  );
}

export function clearProjectAIUserPolicy(
  userId: string,
): Promise<{ user_id: string; changed: boolean }> {
  return apiClient.delete<{ user_id: string; changed: boolean }>(
    `/owner/project-ai/access/users/${userId}`,
  );
}

export function fetchProjectAIProviderFinance(
  providerId: string,
  signal?: AbortSignal,
): Promise<ProjectAIProviderFinance> {
  return apiClient.get<ProjectAIProviderFinance>(
    `/owner/project-ai/providers/${providerId}/finance`,
    { signal },
  );
}

export function updateProjectAIProviderFinance(
  providerId: string,
  updates: ProjectAIProviderFinanceUpdate,
): Promise<ProjectAIProviderFinance> {
  return apiClient.put<ProjectAIProviderFinance>(
    `/owner/project-ai/providers/${providerId}/finance`,
    updates,
  );
}

export type ProjectAIModelRefreshResult = {
  validated: string[];
  unavailable: string[];
  probe_failures: string[];
  revoked: string[];
  observed_at: string;
  ttl_seconds: number;
};

export function refreshProjectAIModelEvidence(): Promise<ProjectAIModelRefreshResult> {
  return apiClient.post<ProjectAIModelRefreshResult>(
    "/owner/project-ai/models/refresh",
    {},
  );
}
