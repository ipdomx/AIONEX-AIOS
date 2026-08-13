import { apiClient } from "@/lib/api-client";

export type CommunicationReadiness = {
  id: "in_app" | "email" | "push" | "telegram" | "whatsapp";
  name: string;
  configured: boolean;
  ready: boolean;
  status: "ready" | "unconfigured";
  reason: string;
  owner_only: boolean;
  capabilities: string[];
};

export type DeliveryStatus =
  | "queued"
  | "retrying"
  | "delivered"
  | "acknowledged"
  | "unconfigured"
  | "dead_letter"
  | "failed"
  | "skipped";

export type CommunicationDelivery = {
  id: string;
  notification_id: string;
  channel: "in_app" | "email" | "push" | "telegram" | "whatsapp";
  status: DeliveryStatus;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  provider_message_id: string | null;
  error_code: string | null;
  delivered_at: string | null;
  acknowledged_at: string | null;
  dead_lettered_at: string | null;
  created_at: string;
  updated_at: string;
};

export type CommunicationOverview = {
  by_status: Record<string, number>;
  by_channel: Record<string, number>;
  readiness: CommunicationReadiness[];
};

export type SupportMessage = {
  id: string;
  support_request_id: string;
  sender_id: string | null;
  visibility: "requester" | "internal";
  message: string;
  attachments: Array<Record<string, unknown>>;
  created_at: string;
};

export type SupportRequest = {
  id: string;
  organization_id: string;
  requester_id: string;
  assigned_to_id: string | null;
  subject: string;
  category: string;
  priority: string;
  status: string;
  message_count: number | null;
  last_message_at: string;
  escalated_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  messages?: SupportMessage[];
};

export type GovernanceOverview = {
  bodies: number;
  policies: number;
  decisions: number;
  pending_approvals: number;
  generated_at: string;
};

export async function fetchCommunicationOverview(
  signal?: AbortSignal,
): Promise<CommunicationOverview> {
  return apiClient.get<CommunicationOverview>(
    "/owner/communications/overview",
    {
      signal,
    },
  );
}

export async function fetchCommunicationDeliveries(
  signal?: AbortSignal,
): Promise<CommunicationDelivery[]> {
  return apiClient.get<CommunicationDelivery[]>(
    "/owner/communications/deliveries",
    { signal },
  );
}

export async function retryCommunicationDelivery(
  deliveryId: string,
): Promise<CommunicationDelivery> {
  return apiClient.post<CommunicationDelivery>(
    `/owner/communications/deliveries/${encodeURIComponent(deliveryId)}/retry`,
  );
}

export async function fetchSupportRequests(
  signal?: AbortSignal,
): Promise<SupportRequest[]> {
  return apiClient.get<SupportRequest[]>("/owner/support/requests", { signal });
}

export async function fetchSupportRequest(
  requestId: string,
  signal?: AbortSignal,
): Promise<SupportRequest> {
  return apiClient.get<SupportRequest>(
    `/owner/support/requests/${encodeURIComponent(requestId)}`,
    { signal },
  );
}

export async function replyToSupportRequest(
  requestId: string,
  payload: { message: string; visibility: "requester" | "internal" },
): Promise<SupportMessage> {
  return apiClient.post<SupportMessage>(
    `/owner/support/requests/${encodeURIComponent(requestId)}/messages`,
    payload,
  );
}

export async function updateSupportRequest(
  requestId: string,
  payload: { status: string; assigned_to_id?: string | null },
): Promise<SupportRequest> {
  return apiClient.patch<SupportRequest>(
    `/owner/support/requests/${encodeURIComponent(requestId)}`,
    payload,
  );
}

export async function deleteSupportRequest(
  requestId: string,
): Promise<{ message: string; request_id: string; deleted_messages: number }> {
  return apiClient.delete<{
    message: string;
    request_id: string;
    deleted_messages: number;
  }>(`/owner/support/requests/${encodeURIComponent(requestId)}`);
}

export async function fetchGovernanceOverview(
  signal?: AbortSignal,
): Promise<GovernanceOverview> {
  return apiClient.get<GovernanceOverview>("/owner/governance/overview", {
    signal,
  });
}

export type SupportTicket = SupportRequest;

export async function fetchOwnerSupportTickets(
  signal?: AbortSignal,
): Promise<SupportTicket[]> {
  return fetchSupportRequests(signal);
}

export async function updateOwnerSupportTicket(
  id: string,
  status:
    | "open"
    | "in_progress"
    | "waiting_user"
    | "resolved"
    | "closed"
    | "suspended"
    | "cancelled",
): Promise<SupportTicket> {
  return updateSupportRequest(id, { status });
}
