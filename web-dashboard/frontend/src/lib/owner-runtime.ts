import { apiClient } from "@/lib/api-client";

export type OwnerProjectStatus =
  | "planning"
  | "active"
  | "paused"
  | "completed"
  | "blocked"
  | "review"
  | "archived"
  | "deleted";

export type OwnerOrganizationStatus =
  "active" | "pending" | "suspended" | "restricted" | "inactive";

export type OwnerUserStatus = "active" | "invited" | "suspended" | "inactive";

export type OwnerProject = {
  id: string;
  name: string;
  organization: string;
  status: OwnerProjectStatus;
  progress: number;
  updatedAt: string;
};

export type OwnerOrganization = {
  id: string;
  name: string;
  users: number;
  projects: number;
  status: OwnerOrganizationStatus;
};

export type OwnerUser = {
  id: string;
  name: string;
  email: string;
  role: string;
  organization: string;
  status: OwnerUserStatus;
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
