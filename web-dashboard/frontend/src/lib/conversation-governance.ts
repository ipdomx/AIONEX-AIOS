import { apiClient } from "@/lib/api-client";

export interface ConversationLimits {
  enabled: boolean;
  max_projects: number;
  max_open_conversations: number;
  max_open_conversations_per_project: number;
  conversation_seconds: number;
  messages_per_conversation: number;
  messages_per_day: number;
  lifetime_message_credits: number;
  max_message_characters: number;
  priority: number;
  default_agent_id: string;
}
export type GovernanceScope = "global" | "plan" | "user";
export interface GovernancePolicy {
  scope: GovernanceScope;
  identifier: string;
  version: number;
  values: Partial<ConversationLimits>;
}
export interface GovernedConversation {
  id: string;
  user_id: string;
  organization_id: string;
  project_id: string;
  title: string;
  status: string;
  messages_used: number;
  opened_at: string;
  version: number;
  last_job_id: string | null;
}
export interface GovernanceDirectory {
  defaults: ConversationLimits;
  policies: GovernancePolicy[];
  users: {
    id: string;
    name: string;
    email: string;
    plan: string;
    status: string;
  }[];
  assistants: {
    id: string;
    name: string;
    model: string;
    provider: string;
    configured: boolean;
  }[];
}
export interface GovernedUsage {
  values: ConversationLimits;
  versions: Record<string, number>;
  usage: { day: string; day_messages: number; total_message_credits: number };
}
const base = "/owner/conversation-governance";
export const governanceApi = {
  get: () => apiClient.get<GovernanceDirectory>(base),
  update: (
    scope: GovernanceScope,
    identifier: string,
    version: number,
    values: Partial<ConversationLimits>,
  ) =>
    apiClient.put<GovernancePolicy>(
      `${base}/policies/${scope}/${encodeURIComponent(identifier)}`,
      { expected_version: version, values },
    ),
  reset: (scope: GovernanceScope, identifier: string, version: number) =>
    apiClient.post<GovernancePolicy>(
      `${base}/policies/${scope}/${encodeURIComponent(identifier)}/reset`,
      { expected_version: version },
    ),
  conversations: (userId?: string) =>
    apiClient.get<GovernedConversation[]>(
      `${base}/conversations${userId ? `?user_id=${encodeURIComponent(userId)}` : ""}`,
    ),
  usage: (userId: string) =>
    apiClient.get<GovernedUsage>(`${base}/users/${encodeURIComponent(userId)}`),
  control: (
    item: GovernedConversation,
    action: "pause" | "resume" | "close",
    note: string,
  ) =>
    apiClient.post<unknown>(
      `${base}/conversations/${encodeURIComponent(item.id)}`,
      { action, user_id: item.user_id, note },
    ),
};
