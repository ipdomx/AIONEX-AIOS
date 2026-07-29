import { apiClient } from "@/lib/api-client";

export type OwnerFinalizationCheck = {
  id: string;
  label: string;
  category:
    "integration" | "security" | "performance" | "reliability" | "usability";
  status: "passed" | "warning" | "failed";
  details: string;
};

export type OwnerFinalizationSnapshot = {
  generatedAt: string;
  completion: number;
  checks: OwnerFinalizationCheck[];
};

export async function fetchOwnerFinalizationSnapshot(
  signal?: AbortSignal,
): Promise<OwnerFinalizationSnapshot> {
  return apiClient.get<OwnerFinalizationSnapshot>("/owner/finalization", {
    signal,
  });
}
