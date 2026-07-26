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
