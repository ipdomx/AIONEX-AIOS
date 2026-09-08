import {
  downloadAuthenticatedBlob,
  request,
} from "@/lib/api";

export type IdentityMediaOperation =
  | "voice_clone"
  | "voice_transform"
  | "face_reenactment"
  | "face_swap"
  | "talking_head"
  | "lip_sync"
  | "avatar_generation";

export type IdentityBasis =
  | "self"
  | "consented_person"
  | "licensed_public_figure"
  | "fictional_inspired";

export type IdentityMediaOperationCapability = {
  operation: IdentityMediaOperation;
  runtime_ready: boolean;
  fictional_inspired_direct: boolean;
  real_person_owner_approval_required: boolean;
  licensed_public_figure_runtime_ready: boolean;
  model: string | null;
  owner_override: null | {
    allowed: boolean;
    identity_bases: Exclude<IdentityBasis, "fictional_inspired">[];
    subject_scope: "any" | "exact";
    subject_reference: string | null;
    version: number;
  };
};

export type IdentityMediaCapabilities = {
  schema: string;
  account_active: boolean;
  operations: IdentityMediaOperationCapability[];
  policy: {
    fictional_inspired: string;
    real_person: string;
    licensed_public_figure: string;
    owner_grant_is_legal_license: boolean;
  };
  provider: string | null;
  worker_live: boolean;
  provider_configured: boolean;
  licensed_public_figure_runtime_ready: boolean;
  free_provider_route_ready: boolean;
  paid_provider_route_ready: boolean;
  raw_credentials_returned: boolean;
};

export type IdentityMediaAccessRequest = {
  request_id: string;
  user_id: string;
  organization_id: string;
  operation: IdentityMediaOperation;
  identity_basis: Exclude<IdentityBasis, "fictional_inspired">;
  subject_reference: string;
  reason: string;
  review_status: "pending" | "approved" | "denied" | "revoked";
  submitted_at: string | null;
  reviewed_at: string | null;
  review_note: string;
  version: number;
};

export type IdentityMediaExecution = {
  execution_id: string;
  operation: IdentityMediaOperation;
  identity_basis: IdentityBasis;
  subject_reference: string;
  status: string;
  provider: string;
  model: string;
  provider_state: string;
  attempts: number;
  max_attempts: number;
  estimated_cost_usd: null;
  max_cost_authorization_usd: number;
  cost_basis: string;
  actual_cost_usd: number | null;
  output_ready: boolean;
  output_media_type: string | null;
  output_size_bytes: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
  rights_evidence_present: boolean;
  license_reference_present: boolean;
};

export function getIdentityMediaCapabilities() {
  return request<IdentityMediaCapabilities>("/studio/identity-media/capabilities");
}

export function getIdentityMediaRequests() {
  return request<{ requests: IdentityMediaAccessRequest[] }>(
    "/studio/identity-media/access-requests",
  );
}

export function requestIdentityMediaAccess(input: {
  operation: IdentityMediaOperation;
  identity_basis: Exclude<IdentityBasis, "fictional_inspired">;
  subject_reference: string;
  reason: string;
}) {
  const body = new FormData();
  body.set("operation", input.operation);
  body.set("identity_basis", input.identity_basis);
  body.set("subject_reference", input.subject_reference);
  body.set("reason", input.reason);
  return request<IdentityMediaAccessRequest>("/studio/identity-media/access-requests", {
    method: "POST",
    body,
  });
}

export function listIdentityMediaExecutions() {
  return request<{ executions: IdentityMediaExecution[] }>(
    "/studio/identity-media/executions",
  );
}

export function createIdentityMediaExecution(body: FormData) {
  return request<IdentityMediaExecution>("/studio/identity-media/executions", {
    method: "POST",
    body,
  });
}

export function downloadIdentityMediaExecution(executionId: string) {
  return downloadAuthenticatedBlob(
    `/studio/identity-media/executions/${encodeURIComponent(executionId)}/download`,
  );
}
