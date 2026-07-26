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
  integrationStatus() {
    return apiClient.get<IntegrationStatus>("/integration/status");
  },
  integrationHealth() {
    return apiClient.get<IntegrationHealth>("/integration/health");
  },
};
