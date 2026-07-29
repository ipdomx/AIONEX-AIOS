import { apiClient } from "@/lib/api-client";
import { executeOwnerResourceAction } from "@/lib/owner-resources";

export type ComplianceControl = {
  id: string;
  framework: string;
  control: string;
  owner: string;
  status:
    | "compliant"
    | "partial"
    | "warning"
    | "non_compliant"
    | "not_applicable"
    | "not_assessed";
  evidence: number;
  updatedAt: string;
};

export async function fetchComplianceControls(
  signal?: AbortSignal,
): Promise<ComplianceControl[]> {
  return apiClient.get<ComplianceControl[]>("/owner/compliance-controls", {
    signal,
  });
}

export async function attestComplianceControl(
  id: string,
): Promise<ComplianceControl> {
  return apiClient.post<ComplianceControl>(
    `/owner/compliance-controls/${encodeURIComponent(id)}/attest`,
  );
}

export async function recordComplianceEvidence(
  id: string,
  reference: string,
): Promise<void> {
  await executeOwnerResourceAction<ComplianceControl>(
    "compliance",
    id,
    "record-evidence",
    { reference },
  );
}
