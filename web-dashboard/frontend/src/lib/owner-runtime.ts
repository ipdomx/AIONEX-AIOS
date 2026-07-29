import { apiClient } from "@/lib/api-client";

export type OwnerProject = {
  id: string;
  name: string;
  organization: string;
  status: "active" | "paused" | "completed" | "blocked";
  progress: number;
  updatedAt: string;
};

export type OwnerOrganization = {
  id: string;
  name: string;
  users: number;
  projects: number;
  status: "active" | "suspended" | "pending";
};

export type OwnerUser = {
  id: string;
  name: string;
  email: string;
  role: string;
  organization: string;
  status: "active" | "suspended" | "invited";
};

export type OwnerRuntimeSnapshot = {
  generatedAt: string;
  projects: OwnerProject[];
  organizations: OwnerOrganization[];
  users: OwnerUser[];
};

export async function fetchOwnerRuntimeSnapshot(
  signal?: AbortSignal,
): Promise<OwnerRuntimeSnapshot> {
  return apiClient.get<OwnerRuntimeSnapshot>("/owner/runtime", { signal });
}
