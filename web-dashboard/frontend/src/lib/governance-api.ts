import { apiClient } from "@/lib/api-client";

export type GovernanceBody = {
  id: string;
  parent_id: string | null;
  owner_user_id: string;
  name: string;
  slug: string;
  kind: "council" | "ministry" | "committee" | "department" | "board";
  status: string;
  charter: string | null;
  jurisdiction: string | null;
  quorum: number;
  created_at: string;
  updated_at: string;
};

export type GovernancePolicy = {
  id: string;
  body_id: string | null;
  code: string;
  title: string;
  description: string | null;
  scope: string;
  enforcement: string;
  status: string;
  enabled: boolean;
  version: number;
  effective_at: string | null;
  retired_at: string | null;
  created_at: string;
  updated_at: string;
};

export type GovernanceDecision = {
  id: string;
  body_id: string | null;
  policy_id: string | null;
  meeting_id: string | null;
  requested_by_id: string;
  decided_by_id: string | null;
  title: string;
  rationale: string | null;
  status: string;
  decision: Record<string, unknown>;
  submitted_at: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
};

export async function fetchGovernanceBodies(
  signal?: AbortSignal,
): Promise<GovernanceBody[]> {
  return apiClient.get<GovernanceBody[]>("/governance/bodies", { signal });
}

export async function createGovernanceBody(payload: {
  name: string;
  kind: GovernanceBody["kind"];
  charter?: string;
  jurisdiction?: string;
  quorum: number;
  parent_id?: string | null;
}): Promise<GovernanceBody> {
  return apiClient.post<GovernanceBody>("/governance/bodies", payload);
}

export async function fetchGovernancePolicies(
  signal?: AbortSignal,
): Promise<GovernancePolicy[]> {
  return apiClient.get<GovernancePolicy[]>("/governance/policies", { signal });
}

export async function createGovernancePolicy(payload: {
  code: string;
  title: string;
  description?: string;
  body_id?: string | null;
  scope: string;
  enforcement: "mandatory" | "advisory" | "informational";
  policy?: Record<string, unknown>;
}): Promise<GovernancePolicy> {
  return apiClient.post<GovernancePolicy>("/governance/policies", payload);
}

export async function submitGovernancePolicy(id: string): Promise<{
  policy: GovernancePolicy;
  approval: { id: string; status: string };
}> {
  return apiClient.post(
    `/governance/policies/${encodeURIComponent(id)}/submit`,
    {},
  );
}

export async function retireGovernancePolicy(
  id: string,
): Promise<GovernancePolicy> {
  return apiClient.post<GovernancePolicy>(
    `/governance/policies/${encodeURIComponent(id)}/retire`,
    {},
  );
}

export async function fetchGovernanceDecisions(
  signal?: AbortSignal,
): Promise<GovernanceDecision[]> {
  return apiClient.get<GovernanceDecision[]>("/governance/decisions", {
    signal,
  });
}

export async function createGovernanceDecision(payload: {
  title: string;
  rationale?: string;
  body_id?: string | null;
  policy_id?: string | null;
  decision?: Record<string, unknown>;
}): Promise<GovernanceDecision> {
  return apiClient.post<GovernanceDecision>("/governance/decisions", payload);
}

export async function submitGovernanceDecision(id: string): Promise<{
  decision: GovernanceDecision;
  approval: { id: string; status: string } | null;
}> {
  return apiClient.post(
    `/governance/decisions/${encodeURIComponent(id)}/submit`,
    {},
  );
}
