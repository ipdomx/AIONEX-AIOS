export type ExecutiveMetric = {
  id: string;
  label: string;
  value: number;
  unit: string;
  trend: number;
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

const fallbackSnapshot: OwnerExecutiveSnapshot = {
  generatedAt: new Date().toISOString(),
  metrics: [
    { id: "revenue", label: "Monthly recurring revenue", value: 128400, unit: "USD", trend: 12.8, status: "good" },
    { id: "projects", label: "Projects on schedule", value: 91, unit: "%", trend: 4.2, status: "good" },
    { id: "availability", label: "Platform availability", value: 99.97, unit: "%", trend: 0.03, status: "good" },
    { id: "incidents", label: "Critical incidents", value: 2, unit: "open", trend: -33, status: "watch" },
  ],
  insights: [
    { id: "capacity", title: "Worker capacity approaching threshold", summary: "Two runtime clusters are above 78% sustained utilization.", severity: "warning", recommendation: "Approve capacity expansion before peak demand." },
    { id: "cost", title: "Provider cost efficiency improved", summary: "Routing optimization reduced model spend per task by 11.4%.", severity: "info", recommendation: "Keep the current routing policy and review again in seven days." },
  ],
};

export async function fetchOwnerExecutiveSnapshot(signal?: AbortSignal): Promise<OwnerExecutiveSnapshot> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_EXECUTIVE_API_URL ?? "/api/owner/executive";

  try {
    const response = await fetch(endpoint, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });

    if (!response.ok) throw new Error(`Owner executive request failed with ${response.status}`);
    const payload = (await response.json()) as Partial<OwnerExecutiveSnapshot>;

    return {
      generatedAt: payload.generatedAt ?? new Date().toISOString(),
      metrics: Array.isArray(payload.metrics) ? payload.metrics : [],
      insights: Array.isArray(payload.insights) ? payload.insights : [],
    };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return { ...fallbackSnapshot, generatedAt: new Date().toISOString() };
  }
}
