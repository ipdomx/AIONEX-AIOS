import { apiClient } from "@/lib/api-client";

export type OwnerTimelineEvent = {
  id: string;
  occurredAt: string;
  actor: string;
  category:
    "project" | "user" | "security" | "approval" | "service" | "incident";
  action: string;
  target: string;
  severity: "info" | "warning" | "critical";
  details: string;
};

export async function fetchOwnerTimeline(
  signal?: AbortSignal,
): Promise<OwnerTimelineEvent[]> {
  const payload = await apiClient.get<{ events: OwnerTimelineEvent[] }>(
    "/owner/timeline",
    {
      signal,
    },
  );
  return payload.events;
}
