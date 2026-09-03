import { apiClient } from "@/lib/api-client";

export type ExternalActivationStatus =
  | "satisfied_runtime"
  | "enforced_internal_external_pending"
  | "blocked_external"
  | "excluded_current_scope";

export type ExternalActivationGate = {
  gate_id: string;
  status: ExternalActivationStatus;
  excluded_from_current_scope: boolean;
  capability_ids: string[];
  batch_ids: string[];
  external_fact: string;
  evidence_requirements: string[];
  internal_controls: string[];
  live_evidence: Record<string, unknown>;
};

export type ExternalActivationSnapshot = {
  generated_at: string;
  scope_policy: {
    store_publication_excluded: boolean;
    direct_apple_pay_excluded: boolean;
    non_registry_exclusions: string[];
  };
  counts: {
    registry_gates: number;
    in_scope_gates: number;
    excluded_current_scope: number;
    satisfied_runtime: number;
    enforced_internal_external_pending: number;
    blocked_external: number;
  };
  gates: ExternalActivationGate[];
  catalog_invariant: {
    missing_definitions: string[];
    orphan_definitions: string[];
  };
};

export function fetchOwnerExternalActivation(signal?: AbortSignal) {
  return apiClient.get<ExternalActivationSnapshot>(
    "/owner/external-activation",
    { signal },
  );
}
