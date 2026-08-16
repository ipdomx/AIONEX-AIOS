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

export type GrowthMetaOwnedTarget = {
  scope_ref: string;
  name: string;
  active: boolean;
  currency: string | null;
  timezone_name: string | null;
};

export type GrowthMetaTargetDiscovery = {
  provider: "meta";
  validation_mode: string;
  graph_api_version: string;
  accounts: GrowthMetaOwnedTarget[];
  account_count: number;
  active_account_count: number;
  result_page_truncated: boolean;
  permissions: {
    ads_read: boolean;
    ads_management: boolean;
    business_management: boolean;
  };
  owned_token_write_ready: boolean;
  provider_call_allowed: boolean;
  provider_write_executed: boolean;
  provider_spend_executed: boolean;
  raw_account_ids_returned: boolean;
  raw_secret_returned: boolean;
};

export function fetchOwnerGrowthMetaTargets(): Promise<GrowthMetaTargetDiscovery> {
  return apiClient.get<GrowthMetaTargetDiscovery>(
    "/owner/growth-social/meta-targets",
  );
}

export type GrowthMetaPage = {
  page_ref: string;
  name: string;
  tasks: string[];
  advertise_ready: boolean;
};

export type GrowthMetaPageDiscovery = {
  provider: "meta";
  validation_mode: string;
  graph_api_version: string;
  pages: GrowthMetaPage[];
  page_count: number;
  advertise_ready_page_count: number;
  result_page_truncated: boolean;
  permissions: {
    pages_show_list: boolean;
    pages_read_engagement: boolean;
    pages_manage_ads: boolean;
    business_management: boolean;
  };
  provider_call_allowed: boolean;
  provider_write_executed: false;
  provider_spend_executed: false;
  raw_page_ids_returned: false;
  raw_secret_returned: false;
};

export function fetchOwnerGrowthMetaPages(): Promise<GrowthMetaPageDiscovery> {
  return apiClient.get<GrowthMetaPageDiscovery>(
    "/owner/growth-social/meta-pages",
  );
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

export function authorizeOwnerGrowthPilotNoSpendWriteValidation(
  pilotId: string,
  reference: string,
): Promise<GrowthControlledPilot> {
  return apiClient.post(
    `/owner/growth-social/pilots/${pilotId}/authorize-no-spend-write-validation`,
    { reference },
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

export type OwnerGrowthPaidCampaign = {
  id: string;
  name: string;
  objective: string;
  status: string;
  approval_status: string;
  owner_approval_required: boolean;
  aios_advice_only: boolean;
  user_budget_preserved: boolean;
  currency: string;
  total_budget_minor: number;
  daily_budget_cap_minor: number;
  simulated_spend_minor: number;
  organization_id: string;
  organization_name?: string;
  created_by_name?: string;
  created_at?: string | null;
  approved_at?: string | null;
  latest_budget_assessment?: Record<string, unknown>;
  configuration_summary?: {
    providers: string[];
    target_countries: string[];
    placements: string[];
    ad_set_count: number;
    creative_count: number;
    ad_count: number;
    creatives: Array<{
      format: string;
      headline: string;
      body: string;
      destination_url: string | null;
    }>;
    truncated: boolean;
    raw_provider_ids_returned: false;
    raw_credentials_returned: false;
  };
  real_spend_allowed: false;
  live_provider_call: false;
  live_campaign_mutation: false;
  automatic_budget_increase_allowed: false;
};

export function fetchOwnerGrowthPaidCampaigns(): Promise<{
  items: OwnerGrowthPaidCampaign[];
  owner_approval_required: true;
  automatic_execution_allowed: false;
  real_spend_allowed: false;
}> {
  return apiClient.get("/owner/growth-social/paid-campaigns");
}

export function approveOwnerGrowthPaidCampaign(
  campaignId: string,
): Promise<OwnerGrowthPaidCampaign> {
  return apiClient.post(
    `/owner/growth-social/paid-campaigns/${campaignId}/approve`,
  );
}

export type OwnerGrowthPaidLivePlan = {
  campaign_id: string;
  pilot_id: string;
  plan_version: string;
  plan_compilable: boolean;
  blocked_reasons: string[];
  owner_approval_gate: boolean;
  organization_gate: boolean;
  pilot_scope_gate: boolean;
  provider_gate: boolean;
  execution_adapter_gate: boolean;
  currency_gate: boolean;
  budget_gate: boolean;
  stop_loss_gate: boolean;
  objective_gate: boolean;
  components_gate: boolean;
  meta_provider_gate: boolean;
  aggregate_budget_gate: boolean;
  reference_gate: boolean;
  destination_gate: boolean;
  creative_identity_gate: boolean;
  creative_identity_ref?: string | null;
  effective_stop_loss: Record<string, unknown>;
  aggregate_adset_daily_budget_minor: number;
  operation_count: number;
  live_legal_gate: boolean;
  launch_gate: boolean;
  runtime_authorization_required: true;
  live_execution_authorized: false;
  provider_call_executed: false;
  spend_executed: false;
  automatic_execution_allowed: false;
  plan_digest?: string;
  plan_persisted?: boolean;
  plan_valid?: boolean;
  plan_digest_matches?: boolean;
};

export function evaluateOwnerGrowthPaidCampaignLivePlan(
  campaignId: string,
  input: { pilot_id: string; creative_identity_ref?: string | null },
): Promise<OwnerGrowthPaidLivePlan> {
  return apiClient.post(
    `/owner/growth-social/paid-campaigns/${campaignId}/live-plan/evaluate`,
    input,
  );
}

export function prepareOwnerGrowthPaidCampaignLivePlan(
  campaignId: string,
  input: { pilot_id: string; creative_identity_ref: string },
): Promise<OwnerGrowthPaidLivePlan> {
  return apiClient.post(
    `/owner/growth-social/paid-campaigns/${campaignId}/live-plan/prepare`,
    input,
  );
}

export function validateOwnerGrowthPaidCampaignLivePlan(
  campaignId: string,
): Promise<OwnerGrowthPaidLivePlan> {
  return apiClient.get(
    `/owner/growth-social/paid-campaigns/${campaignId}/live-plan/validate`,
  );
}

export type OwnerGrowthPaidLiveExecutionStep = {
  step_key: string;
  step_order: number;
  resource_kind: string;
  operation: string;
  status: string;
  attempt_count: number;
  provider_object_ref: string | null;
  manual_review_required: boolean;
  last_error_code: string | null;
};

export type OwnerGrowthPaidLiveExecution = {
  id: string;
  campaign_id: string;
  pilot_id: string;
  provider: "meta";
  scope_ref: string;
  creative_identity_ref: string;
  plan_version: string;
  plan_digest: string;
  status: string;
  authorized: boolean;
  manual_review_required: boolean;
  provider_write_calls_completed: number;
  spend_executed: false;
  automatic_execution_allowed: false;
  raw_provider_object_ids_returned: false;
  steps: OwnerGrowthPaidLiveExecutionStep[];
};

export function fetchOwnerGrowthPaidCampaignLiveExecution(
  campaignId: string,
): Promise<OwnerGrowthPaidLiveExecution> {
  return apiClient.get(
    `/owner/growth-social/paid-campaigns/${campaignId}/live-execution`,
  );
}

export function prepareOwnerGrowthPaidCampaignLiveExecution(
  campaignId: string,
): Promise<OwnerGrowthPaidLiveExecution> {
  return apiClient.post(
    `/owner/growth-social/paid-campaigns/${campaignId}/live-execution/prepare`,
  );
}

export function executeOwnerGrowthPaidCampaignPausedGraph(
  campaignId: string,
  executionId: string,
  input: { plan_digest: string; confirmation: string },
): Promise<OwnerGrowthPaidLiveExecution> {
  return apiClient.post(
    `/owner/growth-social/paid-campaigns/${campaignId}/live-execution/${executionId}/execute-paused`,
    input,
  );
}
