import { apiClient } from "@/lib/api-client";

export type IdentityMediaOperation =
  | "voice_clone"
  | "voice_transform"
  | "face_reenactment"
  | "face_swap"
  | "talking_head"
  | "lip_sync"
  | "avatar_generation";

export type RealIdentityBasis =
  "self" | "consented_person" | "licensed_public_figure";

export type OwnerIdentityMediaAccess = {
  user_id: string;
  user_email: string;
  user_name: string;
  operation: IdentityMediaOperation;
  allowed: boolean;
  identity_bases: RealIdentityBasis[];
  subject_scope: "any" | "exact";
  subject_reference: string | null;
  note: string;
  version: number;
  updated_at: string | null;
};

export type OwnerIdentityMediaRequest = {
  request_id: string;
  user_id: string;
  user_email?: string;
  user_name?: string;
  organization_id: string;
  operation: IdentityMediaOperation;
  identity_basis: RealIdentityBasis;
  subject_reference: string;
  reason: string;
  review_status: "pending" | "approved" | "denied" | "revoked";
  submitted_at: string | null;
  reviewed_at: string | null;
  review_note: string;
  version: number;
};

export type OwnerIdentityMediaUser = {
  id: string;
  email: string;
  name: string;
  status: string;
  organization_id: string;
};

export type OwnerIdentityMediaSnapshot = {
  operations: IdentityMediaOperation[];
  runtime_ready_operations: IdentityMediaOperation[];
  policy: {
    fictional_inspired: string;
    real_person: string;
    licensed_public_figure: string;
    owner_can_grant_deny_revoke_per_user: boolean;
    owner_grant_is_legal_license: boolean;
  };
  access: OwnerIdentityMediaAccess[];
  pending_requests: OwnerIdentityMediaRequest[];
  raw_credentials_returned: boolean;
};

export function getOwnerIdentityMedia(query = "", signal?: AbortSignal) {
  return apiClient.get<OwnerIdentityMediaSnapshot>("/owner/identity-media", {
    params: query ? { query } : undefined,
    signal,
  });
}

export function searchOwnerIdentityMediaUsers(
  query: string,
  signal?: AbortSignal,
) {
  return apiClient.get<{ users: OwnerIdentityMediaUser[] }>(
    "/owner/identity-media/users",
    { params: query ? { query } : undefined, signal },
  );
}

export function listOwnerIdentityMediaRequests(
  status?: OwnerIdentityMediaRequest["review_status"],
  signal?: AbortSignal,
) {
  return apiClient.get<{ requests: OwnerIdentityMediaRequest[] }>(
    "/owner/identity-media/requests",
    { params: status ? { status } : undefined, signal },
  );
}

export function setOwnerIdentityMediaAccess(input: {
  user_id: string;
  operation: IdentityMediaOperation;
  allowed: boolean;
  identity_bases: RealIdentityBasis[];
  subject_scope: "any" | "exact";
  subject_reference?: string | null;
  note?: string;
}) {
  return apiClient.put<OwnerIdentityMediaAccess>(
    "/owner/identity-media/access",
    input,
  );
}

export function clearOwnerIdentityMediaAccess(
  userId: string,
  operation: IdentityMediaOperation,
) {
  return apiClient.delete<{ cleared: boolean }>(
    `/owner/identity-media/access/${encodeURIComponent(userId)}/${encodeURIComponent(operation)}`,
  );
}

export function reviewOwnerIdentityMediaRequest(
  requestId: string,
  decision: "approved" | "denied" | "revoked",
  reviewNote = "",
) {
  return apiClient.put<OwnerIdentityMediaRequest>(
    `/owner/identity-media/requests/${encodeURIComponent(requestId)}`,
    { decision, review_note: reviewNote },
  );
}
