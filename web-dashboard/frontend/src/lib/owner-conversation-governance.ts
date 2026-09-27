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

export const governanceApi = {
  get: () =>
    apiClient.get<GovernanceDirectory>("/owner/conversation-governance"),
  update: (
    scope: GovernanceScope,
    identifier: string,
    version: number,
    values: Partial<ConversationLimits>,
  ) =>
    apiClient.put<GovernancePolicy>(
      `/owner/conversation-governance/policies/${scope}/${encodeURIComponent(identifier)}`,
      { expected_version: version, values },
    ),
  reset: (scope: GovernanceScope, identifier: string, version: number) =>
    apiClient.post<GovernancePolicy>(
      `/owner/conversation-governance/policies/${scope}/${encodeURIComponent(identifier)}/reset`,
      { expected_version: version },
    ),
  conversations: (userId?: string) =>
    apiClient.get<GovernedConversation[]>(
      "/owner/conversation-governance/conversations",
      { params: userId ? { user_id: userId } : undefined },
    ),
  usage: (userId: string) =>
    apiClient.get<GovernedUsage>(
      `/owner/conversation-governance/users/${encodeURIComponent(userId)}`,
    ),
  control: (
    item: GovernedConversation,
    action: "pause" | "resume" | "close",
    note: string,
  ) =>
    apiClient.post<unknown>(
      `/owner/conversation-governance/conversations/${encodeURIComponent(item.id)}`,
      { action, user_id: item.user_id, note },
    ),
};

type NumericKey = Exclude<
  keyof ConversationLimits,
  "enabled" | "default_agent_id"
>;
export const conversationLimitFields: {
  key: NumericKey;
  label: string;
  min: number;
  max: number;
}[] = [
  { key: "max_projects", label: "Projects per user", min: 0, max: 100000 },
  {
    key: "max_open_conversations",
    label: "Concurrent conversations per user",
    min: 0,
    max: 1000,
  },
  {
    key: "max_open_conversations_per_project",
    label: "Concurrent conversations per project",
    min: 0,
    max: 1000,
  },
  {
    key: "conversation_seconds",
    label: "Conversation duration in seconds",
    min: 1,
    max: 31536000,
  },
  {
    key: "messages_per_conversation",
    label: "Messages per conversation",
    min: 0,
    max: 100000,
  },
  {
    key: "messages_per_day",
    label: "Messages per UTC day",
    min: 0,
    max: 1000000,
  },
  {
    key: "lifetime_message_credits",
    label: "Lifetime message credits (-1 = unlimited)",
    min: -1,
    max: 1000000000,
  },
  {
    key: "max_message_characters",
    label: "Characters per message",
    min: 1,
    max: 50000,
  },
  { key: "priority", label: "Dispatch priority (0–100)", min: 0, max: 100 },
];
