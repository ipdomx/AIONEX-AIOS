export type ApprovalStatus = "pending" | "approved" | "rejected" | "changes_requested";

export type OwnerApproval = {
  id: string;
  title: string;
  requester: string;
  scope: string;
  category: "release" | "service" | "policy" | "meeting" | "staff";
  status: ApprovalStatus;
  priority: "low" | "medium" | "high" | "critical";
  createdAt: string;
};

export type ApprovalDecision = {
  status: Exclude<ApprovalStatus, "pending">;
  reason: string;
};

const fallbackApprovals: OwnerApproval[] = [
  { id: "release-2-2", title: "Promote AIOS v2.2.0", requester: "Release Council", scope: "Production", category: "release", status: "pending", priority: "critical", createdAt: "Recently" },
  { id: "provider-openrouter", title: "Enable OpenRouter for customer projects", requester: "AI Platform", scope: "Global", category: "service", status: "pending", priority: "high", createdAt: "Recently" },
  { id: "meeting-chief", title: "Chief engineer review session", requester: "Engineering", scope: "Project AIOS", category: "meeting", status: "pending", priority: "medium", createdAt: "Recently" },
];

export async function fetchOwnerApprovals(signal?: AbortSignal): Promise<OwnerApproval[]> {
  try {
    const response = await fetch("/api/owner/approvals", { cache: "no-store", signal });
    if (!response.ok) throw new Error(`Approvals request failed: ${response.status}`);
    const payload = await response.json() as { approvals?: OwnerApproval[] };
    return Array.isArray(payload.approvals) ? payload.approvals : [];
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return fallbackApprovals;
  }
}

export async function decideOwnerApproval(id: string, decision: ApprovalDecision): Promise<OwnerApproval> {
  const response = await fetch(`/api/owner/approvals/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(decision),
  });

  if (!response.ok) {
    return { ...fallbackApprovals.find((item) => item.id === id)!, status: decision.status };
  }

  return await response.json() as OwnerApproval;
}
