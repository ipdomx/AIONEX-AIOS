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
  started_at: string | null;
  updated_at: string;
  heartbeat_age_seconds: number | null;
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
const READ_TIMEOUT_MS = 12_000;
const WRITE_TIMEOUT_MS = 20_000;

function timed<T>(
  milliseconds: number,
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const timer = globalThis.setTimeout(() => controller.abort(), milliseconds);
  return operation(controller.signal).finally(() => globalThis.clearTimeout(timer));
}

export const conversationApi = {
  policy: () =>
    timed(READ_TIMEOUT_MS, (signal) =>
      request<ConversationUsage>(`${base}/policy`, { signal }),
    ),
  agents: () =>
    timed(READ_TIMEOUT_MS, (signal) =>
      request<ConversationAgent[]>(`${base}/agents`, { signal }),
    ),
  list: () =>
    timed(READ_TIMEOUT_MS, (signal) => request<Conversation[]>(base, { signal })),
  history: (id: string) =>
    timed(READ_TIMEOUT_MS, (signal) =>
      request<ConversationHistory>(
        `${base}/${encodeURIComponent(id)}/messages`,
        { signal },
      ),
    ),
  create: (project_id: string, title: string, request_id: string) =>
    timed(WRITE_TIMEOUT_MS, (signal) =>
      jsonRequest<Conversation>(
        base,
        "POST",
        { project_id, title, request_id },
        { signal },
      ),
    ),
  send: (
    id: string,
    message: string,
    agent_id: string,
    request_id: string,
    confirm_external_processing: boolean,
  ) =>
    timed(WRITE_TIMEOUT_MS, (signal) =>
      jsonRequest<{ job_id: string; status: string; duplicate: boolean }>(
        `${base}/${encodeURIComponent(id)}/messages`,
        "POST",
        { message, agent_id, request_id, confirm_external_processing },
        { signal },
      ),
    ),
  close: (id: string) =>
    timed(WRITE_TIMEOUT_MS, (signal) =>
      jsonRequest<Conversation>(
        `${base}/${encodeURIComponent(id)}/close`,
        "POST",
        undefined,
        { signal },
      ),
    ),
};
