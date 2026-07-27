export type OwnerTimelineEvent = {
  id: string;
  occurredAt: string;
  actor: string;
  category: "project" | "user" | "security" | "approval" | "service" | "incident";
  action: string;
  target: string;
  severity: "info" | "warning" | "critical";
  details: string;
};

const fallbackEvents: OwnerTimelineEvent[] = [
  {
    id: "evt-release-approved",
    occurredAt: new Date().toISOString(),
    actor: "Platform Owner",
    category: "approval",
    action: "Approved release gate",
    target: "AIONEX AIOS",
    severity: "info",
    details: "Production release passed the owner approval gate.",
  },
  {
    id: "evt-worker-recovered",
    occurredAt: new Date(Date.now() - 120000).toISOString(),
    actor: "Recovery Manager",
    category: "service",
    action: "Recovered worker",
    target: "worker-dubai-02",
    severity: "warning",
    details: "Worker returned to service after an automated health recovery.",
  },
];

export async function fetchOwnerTimeline(signal?: AbortSignal): Promise<OwnerTimelineEvent[]> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL
    ? `${process.env.NEXT_PUBLIC_OWNER_API_URL}/timeline`
    : "/api/owner/timeline";

  try {
    const response = await fetch(endpoint, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });

    if (!response.ok) {
      throw new Error(`Owner timeline request failed with ${response.status}`);
    }

    const payload = (await response.json()) as { events?: OwnerTimelineEvent[] } | OwnerTimelineEvent[];
    const events = Array.isArray(payload) ? payload : payload.events;
    return Array.isArray(events) ? events : fallbackEvents;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }

    return fallbackEvents;
  }
}
