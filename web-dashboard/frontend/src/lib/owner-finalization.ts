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

export type OwnerFinalizationSnapshot = {
  generatedAt: string;
  completion: number;
  checks: OwnerFinalizationCheck[];
  program: OwnerCompletionProgram;
};

export async function fetchOwnerFinalizationSnapshot(
  signal?: AbortSignal,
): Promise<OwnerFinalizationSnapshot> {
  return apiClient.get<OwnerFinalizationSnapshot>("/owner/finalization", {
    signal,
  });
}
