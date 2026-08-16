import { apiClient } from "@/lib/api-client";

export type OwnerFinalizationCheck = {
  id: string;
  label: string;
  category:
    "integration" | "security" | "performance" | "reliability" | "usability";
  status: "passed" | "warning" | "failed";
  details: string;
};

export type OwnerCompletionFeature = {
  feature_id: string;
  batch_id: string;
  title: string;
  status: "verified" | "pending" | "deferred";
  acceptance: string[];
  evidence: string[];
};

export type OwnerCompletionBatch = {
  batch_id: string;
  sequence: number;
  title: string;
  status: "complete" | "pending" | "deferred";
  objective: string;
  feature_ids: string[];
  features: OwnerCompletionFeature[];
  verified_features: number;
  total_features: number;
};

export type OwnerCompletionProgram = {
  program: string;
  completion: number;
  verified_features: number;
  actionable_features: number;
  deferred_features: number;
  current_batch: string | null;
  models_providers_batch: string;
  batches: OwnerCompletionBatch[];
};

export const EMPTY_OWNER_COMPLETION_PROGRAM: OwnerCompletionProgram = {
  program: "Phase 29 — Platform Completion Program",
  completion: 0,
  verified_features: 0,
  actionable_features: 0,
  deferred_features: 0,
  current_batch: null,
  models_providers_batch: "29J",
  batches: [],
};

export type Phase36Maturity =
  | "specified"
  | "source_built"
  | "locally_executed"
  | "provider_connected"
  | "runtime_verified"
  | "scaled"
  | "production_ready";

export type OwnerPhase36Capability = {
  capability_id: string;
  category: string;
  title: string;
  owner_batch: string;
  maturity: Phase36Maturity;
  evidence: string[];
  external_gates: string[];
};

export type OwnerPhase36Batch = {
  batch_id: string;
  sequence: number;
  title: string;
  status: "complete" | "in_progress" | "planned";
  capabilities: OwnerPhase36Capability[];
};

export type OwnerPhase36Program = {
  program: string;
  authoritative: boolean;
  minimum_concurrent_users: number;
  current_batch: string | null;
  total_capabilities: number;
  production_ready_capabilities: number;
  completion: number;
  maturity_order: Phase36Maturity[];
  maturity_counts: Record<Phase36Maturity, number>;
  batches: OwnerPhase36Batch[];
};

export const EMPTY_OWNER_PHASE36_PROGRAM: OwnerPhase36Program = {
  program: "Phase 36 — Universal Capability, Creative Media & 1000+ User Scale",
  authoritative: true,
  minimum_concurrent_users: 1000,
  current_batch: "36B",
  total_capabilities: 0,
  production_ready_capabilities: 0,
  completion: 0,
  maturity_order: [
    "specified",
    "source_built",
    "locally_executed",
    "provider_connected",
    "runtime_verified",
    "scaled",
    "production_ready",
  ],
  maturity_counts: {
    specified: 0,
    source_built: 0,
    locally_executed: 0,
    provider_connected: 0,
    runtime_verified: 0,
    scaled: 0,
    production_ready: 0,
  },
  batches: [],
};

export type OwnerFinalizationSnapshot = {
  generatedAt: string;
  completion: number;
  checks: OwnerFinalizationCheck[];
  program: OwnerCompletionProgram;
  phase36: OwnerPhase36Program;
};

export async function fetchOwnerFinalizationSnapshot(
  signal?: AbortSignal,
): Promise<OwnerFinalizationSnapshot> {
  return apiClient.get<OwnerFinalizationSnapshot>("/owner/finalization", {
    signal,
  });
}
