import { apiClient } from "@/lib/api-client";

export type SecurityProfile = "passive" | "standard" | "advanced" | "elite";
export type SecurityAccessLevel =
  "standard" | "advanced" | "elite" | "autonomous" | "owner";

export interface SecurityLabAccess {
  enabled: boolean;
  granted: boolean;
  level: SecurityAccessLevel | null;
  profiles: SecurityProfile[];
  deep_validation_requires_clone: boolean;
}

export interface SecurityTool {
  id: string;
  category: string;
  adapter: string;
  builtin: boolean;
  active: boolean;
  intrusive: boolean;
  requires_source: boolean;
  requires_clone: boolean;
  description: string;
  available: boolean;
}

export interface SecurityTargetRecord {
  id: string;
  project_id: string | null;
  kind: string;
  origin: string;
  hostname: string;
  authorization_status: string;
  verification_method: string;
  active_scan_allowed: boolean;
  status: string;
  metadata: Record<string, unknown>;
  verified_at: string | null;
}

export interface SecurityScanRecord {
  id: string;
  project_id: string | null;
  target_id: string;
  requested_by_id: string | null;
  profile: SecurityProfile;
  status: string;
  execution_mode: string;
  tool_plan: SecurityTool[];
  summary: {
    finding_count?: number;
    severity?: Record<string, number>;
    deep_validation?: Record<string, unknown> | null;
    [key: string]: unknown;
  };
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface SecurityFindingRecord {
  id: string;
  scan_id: string;
  target_id: string;
  source: string;
  category: string;
  title: string;
  severity: string;
  confidence: number;
  state: string;
  fingerprint: string;
  cwe: string | null;
  owasp: string | null;
  location: string | null;
  evidence: Record<string, unknown>;
  remediation: string | null;
  verified_at: string | null;
  resolved_at: string | null;
}

export interface SecurityRemediationRecord {
  id: string;
  project_id: string | null;
  finding_id: string;
  requested_by_id: string | null;
  status: string;
  worktree_ref: string | null;
  plan: Record<string, unknown>;
  regression_result: Record<string, unknown>;
  retest_scan_id: string | null;
  verified_fixed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export const securityLabApi = {
  access(signal?: AbortSignal) {
    return apiClient.get<SecurityLabAccess>("/security-lab/access", { signal });
  },
  tools(signal?: AbortSignal) {
    return apiClient.get<SecurityTool[]>("/security-lab/tools", { signal });
  },
  targets(signal?: AbortSignal) {
    return apiClient.get<SecurityTargetRecord[]>("/security-lab/targets", {
      signal,
    });
  },
  registerManagedTarget(payload: {
    project_id: string;
    origin: string;
    environment: "production" | "staging";
  }) {
    return apiClient.post<SecurityTargetRecord>(
      "/security-lab/targets/managed",
      payload,
    );
  },
  registerExternalTarget(origin: string) {
    return apiClient.post<
      SecurityTargetRecord & {
        verification: { method: string; path: string; challenge: string };
      }
    >("/security-lab/targets/external", { origin });
  },
  verifyExternalTarget(targetId: string, challenge: string) {
    return apiClient.post<SecurityTargetRecord>(
      `/security-lab/targets/${encodeURIComponent(targetId)}/verify`,
      { challenge },
    );
  },
  scans(signal?: AbortSignal) {
    return apiClient.get<SecurityScanRecord[]>("/security-lab/scans", {
      signal,
    });
  },
  createScan(target_id: string, profile: SecurityProfile) {
    return apiClient.post<SecurityScanRecord>("/security-lab/scans", {
      target_id,
      profile,
    });
  },
  cancelScan(scanId: string) {
    return apiClient.post<SecurityScanRecord>(
      `/security-lab/scans/${encodeURIComponent(scanId)}/cancel`,
      {},
    );
  },
  findings(scanId: string, signal?: AbortSignal) {
    return apiClient.get<SecurityFindingRecord[]>(
      `/security-lab/scans/${encodeURIComponent(scanId)}/findings`,
      { signal },
    );
  },
  remediations(signal?: AbortSignal) {
    return apiClient.get<SecurityRemediationRecord[]>(
      "/security-lab/remediations",
      { signal },
    );
  },
  requestRemediation(finding_id: string) {
    return apiClient.post<SecurityRemediationRecord>(
      "/security-lab/remediations",
      { finding_id },
    );
  },
  queueRetest(remediationId: string) {
    return apiClient.post<{
      remediation: SecurityRemediationRecord;
      scan: SecurityScanRecord;
    }>(
      `/security-lab/remediations/${encodeURIComponent(remediationId)}/retest`,
      {},
    );
  },
  finalizeRemediation(remediationId: string) {
    return apiClient.post<SecurityRemediationRecord>(
      `/security-lab/remediations/${encodeURIComponent(remediationId)}/finalize`,
      {},
    );
  },
};
