export type ComplianceControl = {
  id: string;
  framework: string;
  control: string;
  owner: string;
  status: "compliant" | "warning" | "noncompliant";
  evidence: number;
  updatedAt: string;
};

const fallbackControls: ComplianceControl[] = [
  { id: "iso-access", framework: "ISO 27001", control: "Access Control", owner: "Security", status: "compliant", evidence: 12, updatedAt: "Recently" },
  { id: "soc-audit", framework: "SOC 2", control: "Audit Logging", owner: "Platform", status: "warning", evidence: 8, updatedAt: "Recently" },
  { id: "gdpr-retention", framework: "GDPR", control: "Data Retention", owner: "Governance", status: "compliant", evidence: 10, updatedAt: "Recently" },
];

export async function fetchComplianceControls(signal?: AbortSignal): Promise<ComplianceControl[]> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL ?? "/api/owner/compliance-controls";
  try {
    const response = await fetch(endpoint, { cache: "no-store", signal, headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`Compliance request failed with ${response.status}`);
    const payload = await response.json();
    return Array.isArray(payload) ? payload : fallbackControls;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return fallbackControls;
  }
}

export async function attestComplianceControl(id: string): Promise<void> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL ?? "/api/owner/compliance-controls";
  const response = await fetch(`${endpoint}/${id}/attest`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor: "owner" }) });
  if (!response.ok) throw new Error(`Compliance attestation failed with ${response.status}`);
}
