import { apiClient } from "@/lib/api-client";

export interface ProfessionalCitation {
  citation_id: string;
  title: string;
  uri: string;
  source_sha256: string;
}

export interface ProfessionalCase {
  id: string;
  workspace_id: string | null;
  case_mode: string;
  purpose: string;
  subject_ref_hash: string;
  request_summary: string;
  status: string;
  residency_profile: string;
  retention_until: string;
  retention_expired: boolean;
  citations: ProfessionalCitation[];
  assistance: Record<string, unknown>;
  evidence_digest: string;
  human_review_required: boolean;
  autonomous_decision_allowed: boolean;
  review_version: number;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProtectedDataProfiles {
  profiles: Record<
    string,
    {
      residency: string;
      retention_days: number;
      certified: boolean;
      requires_local_legal_validation: boolean;
    }
  >;
  certification_claim: boolean;
  local_legal_validation_required: boolean;
  autonomous_high_stakes_decisions: boolean;
}

export const professionalApi = {
  profiles: () =>
    apiClient.get<ProtectedDataProfiles>("/professional/profiles"),
  listCases: () => apiClient.get<ProfessionalCase[]>("/professional/cases"),
  createCase: (payload: {
    case_mode: string;
    purpose: string;
    subject_reference: string;
    request_summary: string;
    direct_identifiers_removed: boolean;
    residency_profile: string;
    retention_days?: number;
    citations: ProfessionalCitation[];
  }) => apiClient.post<ProfessionalCase>("/professional/cases", payload),
  reviewCase: (caseId: string, decision: string, rationale: string) =>
    apiClient.post<{ case: ProfessionalCase }>(
      `/professional/cases/${encodeURIComponent(caseId)}/review`,
      { decision, rationale },
    ),
  closeCase: (caseId: string) =>
    apiClient.post<ProfessionalCase>(
      `/professional/cases/${encodeURIComponent(caseId)}/close`,
    ),
};
