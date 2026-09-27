import { jsonRequest, request } from "@/lib/api";

export type ConversationPolicy = {
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
};
export type Conversation = {
  id: string;
  project_id: string;
  user_id: string;
  title: string;
  status: string;
  effective_status: string;
  messages_used: number;
  messages_allowed: number;
  opened_at: string;
  expires_at: string;
  seconds_remaining: number;
  version: number;
  last_job_id: string | null;
  priority: number;
};
export type ConversationMessage = {
  id: string;
  ordinal: number;
  user_message: string;
  assistant_message: string | null;
  status: string;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};
export type ConversationHistory = {
  conversation: Conversation;
  messages: ConversationMessage[];
  history_limit: number;
};
export type ConversationUsage = {
  values: ConversationPolicy;
  versions: Record<string, number>;
  credit_unit: string;
  usage: { day: string; day_messages: number; total_message_credits: number };
};
export type ConversationAgent = {
  id: string; name: string; provider: string; model: string;
  external_processing: boolean; platform_shared: boolean;
};
const base = "/project-conversations";
export const conversationApi = {
  policy: () => request<ConversationUsage>(`${base}/policy`),
  agents: () => request<ConversationAgent[]>(`${base}/agents`),
  list: () => request<Conversation[]>(base),
  history: (id: string) => request<ConversationHistory>(`${base}/${encodeURIComponent(id)}/messages`),
  create: (project_id: string, title: string, request_id: string) =>
    jsonRequest<Conversation>(base, "POST", { project_id, title, request_id }),
  send: (id: string, message: string, agent_id: string, request_id: string, confirm_external_processing: boolean) =>
    jsonRequest<{ job_id: string; status: string; duplicate: boolean }>(`${base}/${encodeURIComponent(id)}/messages`, "POST",
      { message, agent_id, request_id, confirm_external_processing }),
  close: (id: string) => jsonRequest<Conversation>(`${base}/${encodeURIComponent(id)}/close`, "POST"),
};
