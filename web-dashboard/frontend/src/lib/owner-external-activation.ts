import { apiClient } from "@/lib/api-client";

export type ExternalActivationStatus =
  | "satisfied_runtime"
  | "satisfied_external_evidence"
  | "enforced_internal_external_pending"
  | "blocked_external"
  | "excluded_current_scope";

export type ExternalActivationOwnerEvidence = {
  review_status: "submitted" | "accepted" | "rejected" | "revoked" | string;
  evidence_reference: string;
  evidence_sha256: string;
  issuer: string;
  expires_at: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  review_note: string;
  version: number;
};

export type ExternalActivationGate = {
  gate_id: string;
  status: ExternalActivationStatus;
  excluded_from_current_scope: boolean;
  capability_ids: string[];
  batch_ids: string[];
  external_fact: string;
  evidence_requirements: string[];
  internal_controls: string[];
  owner_evidence_reviewable: boolean;
  owner_evidence: ExternalActivationOwnerEvidence | null;
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
    satisfied_external_evidence: number;
    enforced_internal_external_pending: number;
    blocked_external: number;
  };
  gates: ExternalActivationGate[];
  catalog_invariant: {
    missing_definitions: string[];
    orphan_definitions: string[];
  };
};

export type ExternalActivationEvidenceSubmit = {
  evidence_reference: string;
  evidence_sha256: string;
  issuer: string;
  expires_at?: string | null;
  notes?: string;
};

export type ExternalActivationEvidenceReview = {
  decision: "accepted" | "rejected" | "revoked";
  review_note?: string;
};

export function fetchOwnerExternalActivation(signal?: AbortSignal) {
  return apiClient.get<ExternalActivationSnapshot>(
    "/owner/external-activation",
    { signal },
  );
}

export function submitOwnerExternalActivationEvidence(
  gateId: string,
  payload: ExternalActivationEvidenceSubmit,
) {
  return apiClient.post<{
    gate_id: string;
    evidence: ExternalActivationOwnerEvidence;
  }>(
    `/owner/external-activation/${encodeURIComponent(gateId)}/evidence`,
    payload,
  );
}

export function reviewOwnerExternalActivationEvidence(
  gateId: string,
  payload: ExternalActivationEvidenceReview,
) {
  return apiClient.put<{
    gate_id: string;
    evidence: ExternalActivationOwnerEvidence;
  }>(
    `/owner/external-activation/${encodeURIComponent(gateId)}/evidence/review`,
    payload,
  );
}
