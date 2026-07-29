import { apiClient } from "@/lib/api-client";

export type ExecutiveMetric = {
  id: string;
  label: string;
  value: number;
  unit: string;
  trend: number | null;
  status: "good" | "watch" | "critical";
};

export type ExecutiveInsight = {
  id: string;
  title: string;
  summary: string;
  severity: "info" | "warning" | "critical";
  recommendation: string;
};

export type OwnerExecutiveSnapshot = {
  generatedAt: string;
  metrics: ExecutiveMetric[];
  insights: ExecutiveInsight[];
};

export async function fetchOwnerExecutiveSnapshot(
  signal?: AbortSignal,
): Promise<OwnerExecutiveSnapshot> {
  return apiClient.get<OwnerExecutiveSnapshot>("/owner/executive", { signal });
}
