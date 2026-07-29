import { apiClient } from "@/lib/api-client";

export type OwnerRealtimeMetric = {
  id: string;
  label: string;
  value: number;
  unit: string;
  status: "healthy" | "warning" | "critical";
  updatedAt: string;
};

export type OwnerRealtimeEvent = {
  id: string;
  source: string;
  message: string;
  severity: "info" | "warning" | "critical";
  createdAt: string;
};

export type OwnerRealtimeSnapshot = {
  generatedAt: string;
  metrics: OwnerRealtimeMetric[];
  events: OwnerRealtimeEvent[];
};

export async function fetchOwnerRealtimeSnapshot(
  signal?: AbortSignal,
): Promise<OwnerRealtimeSnapshot> {
  return apiClient.get<OwnerRealtimeSnapshot>("/owner/realtime", { signal });
}
