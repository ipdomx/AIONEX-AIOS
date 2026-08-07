import { apiClient } from "@/lib/api-client";

export type ReleaseGate = {
  id: string;
  name: string;
  status: "passed" | "warning" | "blocked" | "pending" | "rejected";
  ownerRequired: boolean;
  updatedAt: string;
};

export type ReleaseEvidence = {
  id: string;
  event: "deployment" | "rollback";
  commit: string;
  imageDigests: Record<string, string>;
  validated: boolean;
  note?: string | null;
  recordedBy: string;
  recordedAt: string;
};

export type ReleaseCandidate = {
  id: string;
  version: string;
  environment: "staging" | "production";
  status: "ready" | "blocked" | "deploying" | "released" | "rejected";
  requestedBy: string;
  createdAt: string;
  closed: boolean;
  closedAt: string | null;
  deploymentEvidence?: ReleaseEvidence | null;
  rollbackEvidence?: ReleaseEvidence | null;
  gates: ReleaseGate[];
};

export async function fetchReleaseCandidates(
  signal?: AbortSignal,
): Promise<ReleaseCandidate[]> {
  return apiClient.get<ReleaseCandidate[]>("/owner/releases", { signal });
}

export async function decideRelease(
  candidateId: string,
  decision: "approve" | "reject",
  note: string,
): Promise<ReleaseCandidate> {
  return apiClient.post<ReleaseCandidate>(
    `/owner/releases/${encodeURIComponent(candidateId)}/decision`,
    { decision, note },
  );
}

export async function recordReleaseEvidence(
  candidateId: string,
  payload: {
    event: "deployment" | "rollback";
    commit: string;
    image_digests: Record<string, string>;
    validated: true;
    note?: string;
  },
): Promise<ReleaseEvidence> {
  return apiClient.post<ReleaseEvidence>(
    `/owner/releases/${encodeURIComponent(candidateId)}/evidence`,
    payload,
  );
}
