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

const fallbackSnapshot: OwnerRuntimeSnapshot = {
  generatedAt: new Date(0).toISOString(),
  projects: [
    { id: "aios-core", name: "AIONEX AIOS", organization: "AIONEX", status: "active", progress: 84, updatedAt: "Recently" },
    { id: "owner-console", name: "Owner Control Plane", organization: "AIONEX", status: "active", progress: 78, updatedAt: "Recently" },
  ],
  organizations: [
    { id: "aionex", name: "AIONEX", users: 12, projects: 6, status: "active" },
  ],
  users: [
    { id: "owner", name: "Platform Owner", email: "owner@aionex.local", role: "Owner", organization: "AIONEX", status: "active" },
  ],
};

export async function fetchOwnerRuntimeSnapshot(signal?: AbortSignal): Promise<OwnerRuntimeSnapshot> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL ?? "/api/owner/runtime";

  try {
    const response = await fetch(endpoint, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });

    if (!response.ok) {
      throw new Error(`Owner runtime request failed with ${response.status}`);
    }

    const payload = (await response.json()) as Partial<OwnerRuntimeSnapshot>;
    return {
      generatedAt: payload.generatedAt ?? new Date().toISOString(),
      projects: Array.isArray(payload.projects) ? payload.projects : [],
      organizations: Array.isArray(payload.organizations) ? payload.organizations : [],
      users: Array.isArray(payload.users) ? payload.users : [],
    };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }

    return { ...fallbackSnapshot, generatedAt: new Date().toISOString() };
  }
}
