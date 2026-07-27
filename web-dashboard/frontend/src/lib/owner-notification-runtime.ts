export type NotificationChannel = "in_app" | "email" | "push" | "whatsapp";

export type OwnerNotificationRule = {
  id: string;
  name: string;
  event: string;
  audience: string;
  channels: NotificationChannel[];
  enabled: boolean;
  severity: "info" | "warning" | "critical";
  updatedAt: string;
};

const fallbackRules: OwnerNotificationRule[] = [
  { id: "project-completed", name: "Project completed", event: "project.completed", audience: "owner, organization", channels: ["in_app", "email", "push"], enabled: true, severity: "info", updatedAt: "Recently" },
  { id: "clarification-needed", name: "Clarification required", event: "project.clarification_required", audience: "owner, requester", channels: ["in_app", "email", "push"], enabled: true, severity: "warning", updatedAt: "Recently" },
  { id: "critical-incident", name: "Critical incident", event: "incident.critical", audience: "owner", channels: ["in_app", "email", "push", "whatsapp"], enabled: true, severity: "critical", updatedAt: "Recently" },
];

export async function fetchNotificationRules(signal?: AbortSignal): Promise<OwnerNotificationRule[]> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL ?? "/api/owner/notification-rules";
  try {
    const response = await fetch(endpoint, { cache: "no-store", signal, headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`Notification request failed with ${response.status}`);
    const payload = await response.json();
    return Array.isArray(payload) ? payload : fallbackRules;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return fallbackRules;
  }
}

export async function updateNotificationRule(id: string, payload: Partial<OwnerNotificationRule>): Promise<void> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL ?? "/api/owner/notification-rules";
  const response = await fetch(`${endpoint}/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Notification update failed with ${response.status}`);
}
