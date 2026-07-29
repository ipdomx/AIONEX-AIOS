import { apiClient } from "@/lib/api-client";

export type ReleaseGate = {
  id: string;
  name: string;
  status: "passed" | "warning" | "blocked" | "pending" | "rejected";
  ownerRequired: boolean;
  updatedAt: string;
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
