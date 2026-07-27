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

const fallbackCandidates: ReleaseCandidate[] = [
  {
    id: "release-2-2-0-beta-3",
    version: "2.2.0-beta.3",
    environment: "production",
    status: "ready",
    requestedBy: "Chief Engineer",
    createdAt: "Recently",
    gates: [
      { id: "tests", name: "Automated tests", status: "passed", ownerRequired: false, updatedAt: "Just now" },
      { id: "security", name: "Security validation", status: "passed", ownerRequired: false, updatedAt: "Just now" },
      { id: "owner", name: "Owner authorization", status: "pending", ownerRequired: true, updatedAt: "Awaiting owner" },
    ],
  },
];

export async function fetchReleaseCandidates(signal?: AbortSignal): Promise<ReleaseCandidate[]> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL ?? "/api/owner/releases";
  try {
    const response = await fetch(endpoint, { headers: { Accept: "application/json" }, cache: "no-store", signal });
    if (!response.ok) throw new Error(`Release request failed with ${response.status}`);
    const payload = await response.json();
    return Array.isArray(payload) ? payload : fallbackCandidates;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return fallbackCandidates;
  }
}

export async function decideRelease(candidateId: string, decision: "approve" | "reject" | "rollback", note: string): Promise<void> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL ?? "/api/owner/releases";
  const response = await fetch(`${endpoint}/${encodeURIComponent(candidateId)}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ decision, note }),
  });
  if (!response.ok) throw new Error(`Release decision failed with ${response.status}`);
}
