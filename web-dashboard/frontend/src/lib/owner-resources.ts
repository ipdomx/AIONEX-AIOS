import { apiClient } from "@/lib/api-client";

export type OwnerResourceDomain =
  | "access"
  | "approvals"
  | "audit"
  | "billing"
  | "communications"
  | "compliance"
  | "costs"
  | "executive"
  | "global-command"
  | "governance"
  | "health"
  | "incidents"
  | "integrations"
  | "notifications"
  | "organizations"
  | "policies"
  | "projects"
  | "recovery"
  | "release"
  | "secrets"
  | "services"
  | "staff"
  | "system-map";

export type OwnerResourceCollection<T> = {
  domain: OwnerResourceDomain;
  generatedAt: string;
  items: T[];
};

export async function fetchOwnerResources<T>(
  domain: OwnerResourceDomain,
  signal?: AbortSignal,
): Promise<OwnerResourceCollection<T>> {
  return apiClient.get<OwnerResourceCollection<T>>(
    `/owner/resources/${domain}`,
    { signal },
  );
}

export async function createOwnerResource<T>(
  domain: OwnerResourceDomain,
  payload: Record<string, unknown>,
  id?: string,
): Promise<OwnerResourceCollection<T>> {
  return apiClient.post<OwnerResourceCollection<T>>(
    `/owner/resources/${domain}`,
    { id, payload },
  );
}

export async function executeOwnerResourceAction<T>(
  domain: OwnerResourceDomain,
  resourceId: string,
  action: string,
  payload: Record<string, unknown> = {},
): Promise<OwnerResourceCollection<T>> {
  return apiClient.post<OwnerResourceCollection<T>>(
    `/owner/resources/${domain}/${encodeURIComponent(resourceId)}/actions`,
    { action, payload },
  );
}
