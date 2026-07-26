import { apiClient } from "./api-client";

export interface ProjectSummary {
  id: string;
  name: string;
  slug: string;
  status: string;
  priority: string;
  progress: number;
  workspace: string;
  owner: string;
  team_count: number;
  task_count: number;
  start_date?: string | null;
  end_date?: string | null;
  created_at: string;
}

export interface TaskSummary {
  id: string;
  title: string;
  status: string;
  priority: string;
  assignee?: string | null;
  project?: string | null;
  due_date?: string | null;
  tags: string[];
  created_at: string;
}

export interface WorkflowSummary {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  trigger: string;
  run_count: number;
  last_run_at?: string | null;
  steps: Array<Record<string, unknown>>;
}

export interface MeetingSummary {
  id: string;
  title: string;
  description?: string | null;
  status: string;
  organizer: string;
  start_time: string;
  end_time?: string | null;
  location?: string | null;
  approved_by_owner: boolean;
}

export interface ReportSummary {
  id: string;
  name: string;
  type: string;
  status: string;
  summary?: string | null;
  metrics: Record<string, number>;
  created_at: string;
}

export interface AgentSummary {
  id: string;
  name: string;
  slug: string;
  status: string;
  role: string;
  department: string;
  provider: string;
  provider_id: string;
  model: string;
  tasks_completed: number;
  tasks_failed: number;
  performance: number;
  latency: number;
  cost: number;
  tokens_used: number;
  created_at: string;
}

export interface ProviderSummary {
  id: string;
  name: string;
  type: string;
  status: string;
  latency: number;
  cost_per_1k_tokens: number;
  usage_today: number;
  usage_limit: number;
  last_used?: string | null;
  created_at: string;
  enabled: boolean;
}

export interface JobSummary {
  id: string;
  agent_id: string;
  organization_id: string;
  prompt: string;
  status: string;
  result?: string | null;
  tokens_used: number;
  cost: number;
  latency_ms: number;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface NotificationSummary {
  id: string;
  organization_id: string;
  user_id?: string | null;
  type: string;
  title: string;
  message: string;
  severity: string;
  read: boolean;
  created_at: string;
}

export interface DashboardStats {
  total_workspaces: number;
  total_projects: number;
  active_projects: number;
  total_tasks: number;
  completed_tasks: number;
  in_progress_tasks: number;
  todo_tasks: number;
  total_workflows: number;
  active_workflows: number;
  total_meetings: number;
  pending_meetings: number;
  total_reports: number;
  average_project_progress: number;
  activity_count: number;
}

export interface IntegrationStatus {
  available: boolean;
  version: string;
  root: string;
  modules: Record<string, boolean>;
  error?: string | null;
}

export interface IntegrationHealth {
  status: "healthy" | "degraded";
  version: string;
  platforms: Record<string, boolean>;
}

export const runtimeServices = {
  listProjects(params?: { status?: string; search?: string; limit?: number }) {
    return apiClient.get<ProjectSummary[]>("/projects", { params });
  },
  listTasks(params?: { status?: string; project_id?: string; search?: string; limit?: number }) {
    return apiClient.get<TaskSummary[]>("/tasks", { params });
  },
  listWorkflows(params?: { status?: string; project_id?: string; limit?: number }) {
    return apiClient.get<WorkflowSummary[]>("/workflows", { params });
  },
  runWorkflow(workflowId: string) {
    return apiClient.post<{ run_id: string; status: string }>(`/workflows/${workflowId}/run`);
  },
  listMeetings(params?: { status?: string; project_id?: string; limit?: number }) {
    return apiClient.get<MeetingSummary[]>("/meetings", { params });
  },
  listReports(params?: { type?: string; project_id?: string; limit?: number }) {
    return apiClient.get<ReportSummary[]>("/reports", { params });
  },
  listAgents(params?: { status?: string; provider?: string; role?: string; search?: string; limit?: number }) {
    return apiClient.get<AgentSummary[]>("/ai/agents", { params });
  },
  createAgent(data: Record<string, unknown>) {
    return apiClient.post<AgentSummary>("/ai/agents", data);
  },
  executeAgent(agentId: string, prompt: string) {
    return apiClient.post<JobSummary>(`/ai/agents/${agentId}/execute`, { prompt });
  },
  listProviders() {
    return apiClient.get<ProviderSummary[]>("/ai/providers");
  },
  createProvider(data: Record<string, unknown>) {
    return apiClient.post<ProviderSummary>("/ai/providers", data);
  },
  testProvider(providerId: string) {
    return apiClient.post<{ status: string; latency_ms: number; message: string }>(`/ai/providers/${providerId}/test`);
  },
  listNotifications(unreadOnly = false) {
    return apiClient.get<NotificationSummary[]>("/notifications", { params: { unread_only: unreadOnly } });
  },
  markNotification(notificationId: string, read = true) {
    return apiClient.request<NotificationSummary>({ method: "PATCH", url: `/notifications/${notificationId}`, data: { read } });
  },
  dashboardStats() {
    return apiClient.get<DashboardStats>("/dashboard/stats");
  },
  dashboardActivity(limit = 20) {
    return apiClient.get<Array<Record<string, unknown>>>("/dashboard/activity", { params: { limit } });
  },
  dashboardCharts() {
    return apiClient.get<Record<string, { labels: string[]; data: number[] }>>("/dashboard/charts");
  },
  integrationStatus() {
    return apiClient.get<IntegrationStatus>("/integration/status");
  },
  integrationHealth() {
    return apiClient.get<IntegrationHealth>("/integration/health");
  },
};
