import { apiClient } from "@/lib/api-client";

export type ComplianceControl = {
  id: string;
  framework: string;
  control: string;
  owner: string;
  status: "compliant" | "warning" | "noncompliant";
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
