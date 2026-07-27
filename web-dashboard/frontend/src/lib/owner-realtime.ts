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

const fallbackSnapshot: OwnerRealtimeSnapshot = {
  generatedAt: new Date().toISOString(),
  metrics: [
    { id: "workers", label: "Active workers", value: 18, unit: "workers", status: "healthy", updatedAt: "Now" },
    { id: "queues", label: "Queued jobs", value: 7, unit: "jobs", status: "healthy", updatedAt: "Now" },
    { id: "latency", label: "API latency", value: 142, unit: "ms", status: "warning", updatedAt: "Now" },
    { id: "errors", label: "Error rate", value: 0.4, unit: "%", status: "healthy", updatedAt: "Now" },
  ],
  events: [
    { id: "evt-1", source: "Runtime", message: "Owner realtime channel initialized.", severity: "info", createdAt: "Now" },
    { id: "evt-2", source: "API Gateway", message: "Latency exceeded preferred threshold.", severity: "warning", createdAt: "1m ago" },
  ],
};

export async function fetchOwnerRealtimeSnapshot(signal?: AbortSignal): Promise<OwnerRealtimeSnapshot> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_REALTIME_API_URL ?? "/api/owner/realtime";

  try {
    const response = await fetch(endpoint, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });

    if (!response.ok) {
      throw new Error(`Owner realtime request failed with ${response.status}`);
    }

    const payload = (await response.json()) as Partial<OwnerRealtimeSnapshot>;
    return {
      generatedAt: payload.generatedAt ?? new Date().toISOString(),
      metrics: Array.isArray(payload.metrics) ? payload.metrics : [],
      events: Array.isArray(payload.events) ? payload.events : [],
    };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }

    return { ...fallbackSnapshot, generatedAt: new Date().toISOString() };
  }
}
