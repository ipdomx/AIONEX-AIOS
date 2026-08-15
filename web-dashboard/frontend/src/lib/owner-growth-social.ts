import { apiClient } from "@/lib/api-client";

export type GrowthCapabilityDefinition = {
  id: string;
  default_entitlements?: string[];
  approval_default?: boolean;
};

export type GrowthAccessOverrideInput = {
  scope: "user" | "organization";
  subject_id: string;
  capability: string;
  allowed: boolean;
  approval_required?: boolean;
  limits?: Record<string, unknown>;
};

export type GrowthAccessDecision = {
  capability: string;
  allowed: boolean;
  source: string;
  reason: string;
  approval_required: boolean;
  limits: Record<string, unknown>;
};

export type GrowthAccessOverride = {
  record_id: string;
  scope: "user" | "organization";
  subject_id: string;
  subject_name: string | null;
  subject_detail: string | null;
  subject_status: string;
  capability: string;
  allowed: boolean;
  approval_required: boolean;
  limits: Record<string, unknown>;
  limits_redacted: boolean;
  record_enabled: boolean;
  version: number;
  updated_at: string | null;
};

export type GrowthAccessOverrideList = {
  items: GrowthAccessOverride[];
  invalid_records: number;
  provider_write_executed: boolean;
  provider_spend_executed: boolean;
  raw_credentials_returned: boolean;
};

export function fetchOwnerGrowthCapabilities(): Promise<
  GrowthCapabilityDefinition[]
> {
  return apiClient.get<GrowthCapabilityDefinition[]>(
    "/owner/growth-social/capabilities",
  );
}

export function fetchOwnerGrowthAccessOverrides(): Promise<GrowthAccessOverrideList> {
  return apiClient.get<GrowthAccessOverrideList>("/owner/growth-social/access");
}

export function setOwnerGrowthAccess(
  input: GrowthAccessOverrideInput,
): Promise<GrowthAccessDecision> {
  return apiClient.put<GrowthAccessDecision>(
    "/owner/growth-social/access",
    input,
  );
}

export function clearOwnerGrowthAccess(input: {
  scope: "user" | "organization";
  subject_id: string;
  capability: string;
}): Promise<{ cleared: boolean }> {
  return apiClient.delete<{ cleared: boolean }>("/owner/growth-social/access", {
    params: input,
  });
}

export type GrowthControlledPilot = {
  id: string;
  organization_id: string | null;
  provider: "meta" | "telegram";
  provider_scope: string;
  scope_ref: string | null;
  mode: "read_only" | "live_spend";
  capability: string;
  status: string;
  owner_approved: boolean;
  owner_approval_reference: string | null;
  legal_policy_acknowledged: boolean;
  legal_policy_reference: string | null;
  currency: string | null;
  max_total_budget_minor: number | null;
  max_daily_budget_minor: number | null;
  max_cpa_minor: number | null;
  min_roas: number | null;
  launch_authorized: boolean;
  expires_at: string | null;
  live_provider_mutation_allowed: boolean;
  real_spend_allowed: boolean;
  automatic_execution_allowed: boolean;
  blocked_reasons: string[];
  evidence: Record<string, unknown>;
};

export type GrowthPilotReadiness = {
  pilot_id: string;
  mode: "read_only" | "live_spend";
  provider: string;
  capability: string;
  provider_verification_state: string;
  owner_gate: boolean;
  organization_gate: boolean;
  provider_scope_gate: boolean;
  provider_gate: boolean;
  execution_adapter_gate: boolean;
  legal_gate: boolean;
  budget_gate: boolean;
  stop_loss_gate: boolean;
  expiry_gate: boolean;
  launch_gate: boolean;
  ready_to_arm: boolean;
  blocked_reasons: string[];
  live_provider_mutation_allowed: boolean;
  real_spend_allowed: boolean;
  automatic_execution_allowed: boolean;
};

export function fetchOwnerGrowthPilots(): Promise<{
  items: GrowthControlledPilot[];
  provider_write_executed: boolean;
  provider_spend_executed: boolean;
}> {
  return apiClient.get("/owner/growth-social/pilots");
}

export function createOwnerGrowthPilot(input: {
  organization_id?: string | null;
  provider: "meta" | "telegram";
  provider_scope: string;
  scope_ref?: string | null;
  mode: "read_only" | "live_spend";
  owner_approval_reference: string;
  expires_at?: string | null;
}): Promise<GrowthControlledPilot> {
  return apiClient.post("/owner/growth-social/pilots", input);
}

export function fetchOwnerGrowthPilotReadiness(
  pilotId: string,
): Promise<GrowthPilotReadiness> {
  return apiClient.get(`/owner/growth-social/pilots/${pilotId}/readiness`);
}

export function configureOwnerGrowthPilot(
  pilotId: string,
  input: {
    legal_policy_acknowledged?: boolean;
    legal_policy_reference?: string | null;
    currency?: string | null;
    max_total_budget_minor?: number | null;
    max_daily_budget_minor?: number | null;
    max_cpa_minor?: number | null;
    min_roas?: number | null;
    expires_at?: string | null;
  },
): Promise<GrowthControlledPilot> {
  return apiClient.patch(
    `/owner/growth-social/pilots/${pilotId}/controls`,
    input,
  );
}

export function validateOwnerGrowthPilotReadOnly(
  pilotId: string,
): Promise<GrowthControlledPilot> {
  return apiClient.post(
    `/owner/growth-social/pilots/${pilotId}/validate-read-only`,
  );
}

export function authorizeOwnerGrowthPilotLaunch(
  pilotId: string,
): Promise<GrowthControlledPilot> {
  return apiClient.post(
    `/owner/growth-social/pilots/${pilotId}/authorize-launch`,
  );
}

export function armOwnerGrowthPilot(
  pilotId: string,
): Promise<GrowthControlledPilot> {
  return apiClient.post(`/owner/growth-social/pilots/${pilotId}/arm`);
}

export function disarmOwnerGrowthPilot(
  pilotId: string,
  reason = "owner-disarm",
): Promise<GrowthControlledPilot> {
  return apiClient.post(`/owner/growth-social/pilots/${pilotId}/disarm`, {
    reason,
  });
}
