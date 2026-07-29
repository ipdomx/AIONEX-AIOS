import { apiClient } from "@/lib/api-client";

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

export async function fetchNotificationRules(
  signal?: AbortSignal,
): Promise<OwnerNotificationRule[]> {
  return apiClient.get<OwnerNotificationRule[]>("/owner/notification-rules", {
    signal,
  });
}

export async function updateNotificationRule(
  id: string,
  payload: Partial<OwnerNotificationRule>,
): Promise<OwnerNotificationRule> {
  return apiClient.patch<OwnerNotificationRule>(
    `/owner/notification-rules/${encodeURIComponent(id)}`,
    payload,
  );
}
