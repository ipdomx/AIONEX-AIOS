import { apiClient } from "@/lib/api-client";
import type {
  SecurityFindingRecord,
  SecurityScanRecord,
  SecurityTargetRecord,
} from "@/lib/security-lab";

export interface SecurityLabPolicy {
  enabled: boolean;
  managed_domain_suffixes: string[];
  max_concurrent_scans_per_user: number;
  max_scan_runtime_seconds: number;
  active_on_verified_targets: boolean;
  deep_validation_requires_clone: boolean;
  learning_enabled: boolean;
  auto_rule_candidates: boolean;
  auto_remediation_enabled: boolean;
  release_gate: {
    block_confirmed_critical: boolean;
    block_confirmed_high: boolean;
    max_confirmed_medium: number;
    require_tls: boolean;
    require_security_headers: boolean;
    require_backup_restore_evidence: boolean;
  };
}

export interface SecurityGrantRecord {
  id: string;
  user_id: string;
  level: "standard" | "advanced" | "elite" | "autonomous";
  status: string;
  profiles: string[];
  notes: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface SecurityLabOwnerSnapshot {
  policy: SecurityLabPolicy;
  grants: SecurityGrantRecord[];
  targets: SecurityTargetRecord[];
}

export interface SecurityEligibleProject {
  id: string;
  name: string;
  status: string;
  owner_id: string;
}

export interface SecurityEligibleUser {
  id: string;
  name: string;
  email: string;
  status: string;
  role: string;
}

export interface SecurityRuleRecord {
  id: string;
  source_finding_id: string | null;
  rule_type: string;
  name: string;
  signature: string;
  detector: Record<string, unknown>;
  status: string;
  trust_score: number;
  validation_passes: number;
  validation_failures: number;
  promoted_at: string | null;
}

export interface SecurityReleaseGateRecord {
  id: string;
  project_id: string | null;
  scan_id: string;
  decision: string;
  policy_snapshot: Record<string, unknown>;
  blockers: Array<Record<string, unknown>>;
  created_by_id: string | null;
  created_at: string | null;
}

export const ownerSecurityLabApi = {
  snapshot(signal?: AbortSignal) {
    return apiClient.get<SecurityLabOwnerSnapshot>("/owner/security-lab", {
      signal,
    });
  },
  users(signal?: AbortSignal) {
    return apiClient.get<SecurityEligibleUser[]>(
      "/owner/security-lab/eligible-users",
      { signal },
    );
  },
  projects(signal?: AbortSignal) {
    return apiClient.get<SecurityEligibleProject[]>(
      "/owner/security-lab/eligible-projects",
      { signal },
    );
  },
  registerManagedTarget(payload: {
    project_id: string;
    origin: string;
    environment: "production" | "staging";
  }) {
    return apiClient.post<SecurityTargetRecord>(
      "/owner/security-lab/managed-targets",
      payload,
    );
  },
  updatePolicy(updates: Partial<SecurityLabPolicy>) {
    return apiClient.patch<SecurityLabPolicy>(
      "/owner/security-lab/policy",
      updates,
    );
  },
  registerCloneTarget(source_target_id: string, origin: string) {
    return apiClient.post<SecurityTargetRecord>(
      "/owner/security-lab/clone-targets",
      {
        source_target_id,
        origin,
      },
    );
  },
  grant(payload: {
    user_id: string;
    level: SecurityGrantRecord["level"];
    profiles?: string[];
    notes?: string;
  }) {
    return apiClient.post<SecurityGrantRecord>(
      "/owner/security-lab/grants",
      payload,
    );
  },
  revoke(userId: string) {
    return apiClient.post<SecurityGrantRecord>(
      `/owner/security-lab/grants/${encodeURIComponent(userId)}/revoke`,
      {},
    );
  },
  findings(signal?: AbortSignal) {
    return apiClient.get<SecurityFindingRecord[]>(
      "/owner/security-lab/findings",
      { signal },
    );
  },
  decideFinding(
    findingId: string,
    state: "confirmed" | "false_positive" | "resolved",
  ) {
    return apiClient.post<{
      finding_id: string;
      state: string;
      rule: SecurityRuleRecord | null;
    }>(
      `/owner/security-lab/findings/${encodeURIComponent(findingId)}/decision`,
      { state },
    );
  },
  rules(signal?: AbortSignal) {
    return apiClient.get<SecurityRuleRecord[]>("/owner/security-lab/rules", {
      signal,
    });
  },
  validateRule(ruleId: string) {
    return apiClient.post<SecurityRuleRecord>(
      `/owner/security-lab/rules/${encodeURIComponent(ruleId)}/validate`,
      {},
    );
  },
  promoteRule(ruleId: string) {
    return apiClient.post<SecurityRuleRecord>(
      `/owner/security-lab/rules/${encodeURIComponent(ruleId)}/promote`,
      {},
    );
  },
  releaseGates(signal?: AbortSignal) {
    return apiClient.get<SecurityReleaseGateRecord[]>(
      "/owner/security-lab/release-gates",
      { signal },
    );
  },
  evaluateReleaseGate(scan_id: string) {
    return apiClient.post<SecurityReleaseGateRecord>(
      "/owner/security-lab/release-gates",
      { scan_id },
    );
  },
  scans(signal?: AbortSignal) {
    return apiClient.get<SecurityScanRecord[]>("/owner/security-lab/scans", {
      signal,
    });
  },
};
