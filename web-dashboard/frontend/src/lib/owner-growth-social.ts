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

export function fetchOwnerGrowthCapabilities(): Promise<
  GrowthCapabilityDefinition[]
> {
  return apiClient.get<GrowthCapabilityDefinition[]>(
    "/owner/growth-social/capabilities",
  );
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
