import { apiClient } from "@/lib/api-client";

export type ApprovalStatus =
  "pending" | "approved" | "rejected" | "changes_requested";

export type OwnerApproval = {
  id: string;
  title: string;
  requester: string;
  scope: string;
  category: "meeting";
  status: ApprovalStatus;
  priority: "low" | "medium" | "high" | "critical";
  createdAt: string;
};

export type ApprovalDecision = {
  status: Exclude<ApprovalStatus, "pending">;
  reason: string;
};

export async function fetchOwnerApprovals(
  signal?: AbortSignal,
): Promise<OwnerApproval[]> {
  const payload = await apiClient.get<{ approvals: OwnerApproval[] }>(
    "/owner/approvals",
    {
      signal,
    },
  );
  return payload.approvals;
}

export async function decideOwnerApproval(
  id: string,
  decision: ApprovalDecision,
): Promise<OwnerApproval> {
  return apiClient.patch<OwnerApproval>(
    `/owner/approvals/${encodeURIComponent(id)}`,
    decision,
  );
}
