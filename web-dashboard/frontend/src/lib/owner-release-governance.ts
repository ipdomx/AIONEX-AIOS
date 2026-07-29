import { apiClient } from "@/lib/api-client";

export type ReleaseGate = {
  id: string;
  name: string;
  status: "passed" | "warning" | "blocked" | "pending";
  ownerRequired: boolean;
  updatedAt: string;
};

export type ReleaseCandidate = {
  id: string;
  version: string;
  environment: "staging" | "production";
  status: "ready" | "blocked" | "deploying" | "released";
  requestedBy: string;
  createdAt: string;
  gates: ReleaseGate[];
};

export async function fetchReleaseCandidates(
  signal?: AbortSignal,
): Promise<ReleaseCandidate[]> {
  return apiClient.get<ReleaseCandidate[]>("/owner/releases", { signal });
}

export async function decideRelease(
  candidateId: string,
  decision: "approve" | "reject" | "rollback",
  note: string,
): Promise<ReleaseCandidate> {
  return apiClient.post<ReleaseCandidate>(
    `/owner/releases/${encodeURIComponent(candidateId)}/decision`,
    { decision, note },
  );
}
