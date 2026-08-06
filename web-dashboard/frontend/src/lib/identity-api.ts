import { apiClient } from "@/lib/api-client";

export type IdentityUser = {
  id: string;
  email: string;
  name: string;
  avatar: string | null;
  role: string;
  role_id: string;
  permissions: string[];
  status: string;
  organization: string;
  organization_id: string;
  workspace: string | null;
  workspace_id: string | null;
  last_active: string | null;
  created_at: string;
  updated_at: string;
};

export type OrganizationRecord = {
  id: string;
  name: string;
  slug: string;
  plan: string;
  status: string;
  owner_user_id: string | null;
  member_count: number;
  role_count: number;
  created_at: string;
  updated_at: string;
};

export type WorkspaceRecord = {
  id: string;
  name: string;
  slug: string;
  organization_id: string;
  description: string | null;
  status: string;
};

export type PermissionRecord = {
  id: string;
  code: string;
  description: string | null;
};

export type RoleRecord = {
  id: string;
  organization_id: string | null;
  organization: string | null;
  name: string;
  description: string | null;
  system: boolean;
  status: string;
  permissions: string[];
  user_count?: number;
};

export type TeamRecord = {
  id: string;
  organization_id: string;
  workspace_id: string | null;
  workspace: string | null;
  name: string;
  slug: string;
  description: string | null;
  status: string;
  member_count: number;
  created_at: string;
  updated_at: string;
};

export const identityApi = {
  users: () => apiClient.get<IdentityUser[]>("/users?limit=100"),
  createUser: (payload: {
    email: string;
    name: string;
    password?: string;
    role_id: string;
    organization_id: string;
    workspace_id?: string | null;
  }) =>
    apiClient.post<{ user: IdentityUser; temporary_password: string | null }>(
      "/users",
      payload,
    ),
  updateUser: (id: string, payload: Record<string, unknown>) =>
    apiClient.put<IdentityUser>(`/users/${encodeURIComponent(id)}`, payload),
  deleteUser: (id: string) =>
    apiClient.delete<{ message: string }>(`/users/${encodeURIComponent(id)}`),

  organizations: () =>
    apiClient.get<OrganizationRecord[]>("/organizations?limit=100"),
  createOrganization: (payload: {
    name: string;
    slug?: string;
    plan?: string;
  }) => apiClient.post<OrganizationRecord>("/organizations", payload),
  updateOrganization: (id: string, payload: Record<string, unknown>) =>
    apiClient.put<OrganizationRecord>(
      `/organizations/${encodeURIComponent(id)}`,
      payload,
    ),
  deactivateOrganization: (id: string) =>
    apiClient.delete<{ message: string }>(
      `/organizations/${encodeURIComponent(id)}`,
    ),

  workspaces: () => apiClient.get<WorkspaceRecord[]>("/workspaces"),

  teams: () => apiClient.get<TeamRecord[]>("/teams"),
  createTeam: (payload: {
    name: string;
    organization_id?: string;
    description?: string;
    workspace_id?: string | null;
  }) => apiClient.post<TeamRecord>("/teams", payload),
  updateTeam: (id: string, payload: Record<string, unknown>) =>
    apiClient.put<TeamRecord>(`/teams/${encodeURIComponent(id)}`, payload),
  deleteTeam: (id: string) =>
    apiClient.delete<{ message: string }>(`/teams/${encodeURIComponent(id)}`),
  teamMembers: (id: string) =>
    apiClient.get<Array<IdentityUser & { membership_role: "lead" | "member" }>>(
      `/teams/${encodeURIComponent(id)}/members`,
    ),
  upsertTeamMember: (
    teamId: string,
    userId: string,
    membershipRole: "lead" | "member",
  ) =>
    apiClient.put<{
      team_id: string;
      user_id: string;
      membership_role: string;
    }>(
      `/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}`,
      { membership_role: membershipRole },
    ),
  removeTeamMember: (teamId: string, userId: string) =>
    apiClient.delete<{ message: string }>(
      `/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}`,
    ),

  roles: () => apiClient.get<RoleRecord[]>("/roles"),
  createRole: (payload: {
    name: string;
    description?: string;
    organization_id?: string;
    permissions: string[];
  }) => apiClient.post<RoleRecord>("/roles", payload),
  updateRole: (id: string, payload: Record<string, unknown>) =>
    apiClient.put<RoleRecord>(`/roles/${encodeURIComponent(id)}`, payload),
  deleteRole: (id: string) =>
    apiClient.delete<{ message: string }>(`/roles/${encodeURIComponent(id)}`),

  permissions: () =>
    apiClient.get<PermissionRecord[]>("/permissions/catalogue"),
};
