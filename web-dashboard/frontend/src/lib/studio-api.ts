import { apiClient } from "@/lib/api-client";

export type StudioDepartment = {
  id: string;
  name: string;
  asset_type: string;
  outputs: string[];
};

export type StudioJob = {
  id: string;
  project_id: string | null;
  revision_of_asset_id: string | null;
  department: string;
  output_kind: string;
  title: string;
  brief: string;
  language: string;
  style: string;
  target: string | null;
  programming_language: string | null;
  change_note: string | null;
  provider_mode: "provider_neutral";
  provider: null;
  model: null;
  status: string;
  progress: number;
  safety_status: string;
  safety_findings: Array<Record<string, unknown>>;
  result_metadata: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  attempts: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
};

export type StudioAsset = {
  id: string;
  job_id: string;
  project_id: string | null;
  department: string;
  asset_type: string;
  title: string;
  filename: string;
  media_type: string;
  checksum: string;
  size_bytes: number;
  status: string;
  current_revision: number;
  metadata: Record<string, unknown>;
  attached_project_ids: string[];
  created_at: string;
  updated_at: string;
};

export type StudioRevision = {
  id: string;
  asset_id: string;
  job_id: string;
  revision_number: number;
  filename: string;
  checksum: string;
  size_bytes: number;
  change_note: string | null;
  status: string;
  created_at: string;
};

export type ProjectOption = { id: string; name: string };

export async function getStudioDepartments(): Promise<{
  departments: StudioDepartment[];
  provider_mode: string;
  provider_activation_batch: string;
}> {
  return apiClient.get("/studio/departments");
}

export async function createStudioJob(
  payload: Record<string, unknown>,
): Promise<StudioJob> {
  return apiClient.post<StudioJob>("/studio/jobs", payload);
}

export async function listStudioJobs(): Promise<StudioJob[]> {
  return apiClient.get<StudioJob[]>("/studio/jobs", {
    params: { limit: 100 },
  });
}

export async function getStudioJob(jobId: string): Promise<StudioJob> {
  return apiClient.get<StudioJob>(`/studio/jobs/${encodeURIComponent(jobId)}`);
}

export async function retryStudioJob(jobId: string): Promise<StudioJob> {
  return apiClient.post<StudioJob>(
    `/studio/jobs/${encodeURIComponent(jobId)}/retry`,
    {},
  );
}

export async function cancelStudioJob(jobId: string): Promise<StudioJob> {
  return apiClient.post<StudioJob>(
    `/studio/jobs/${encodeURIComponent(jobId)}/cancel`,
    {},
  );
}

export async function listStudioAssets(): Promise<StudioAsset[]> {
  return apiClient.get<StudioAsset[]>("/studio/assets", {
    params: { limit: 100 },
  });
}

export async function listStudioRevisions(
  assetId: string,
): Promise<StudioRevision[]> {
  return apiClient.get<StudioRevision[]>(
    `/studio/assets/${encodeURIComponent(assetId)}/revisions`,
  );
}

export async function createStudioRevision(
  assetId: string,
  payload: Record<string, unknown>,
): Promise<StudioJob> {
  return apiClient.post<StudioJob>(
    `/studio/assets/${encodeURIComponent(assetId)}/revisions`,
    payload,
  );
}

export async function attachStudioAsset(
  assetId: string,
  projectId: string,
): Promise<void> {
  await apiClient.post(`/studio/assets/${encodeURIComponent(assetId)}/attach`, {
    project_id: projectId,
  });
}

export async function archiveStudioAsset(
  assetId: string,
): Promise<StudioAsset> {
  return apiClient.post<StudioAsset>(
    `/studio/assets/${encodeURIComponent(assetId)}/archive`,
    {},
  );
}

export async function downloadStudioAsset(
  assetId: string,
  revision?: number,
): Promise<Blob> {
  return apiClient.get<Blob>(
    `/studio/assets/${encodeURIComponent(assetId)}/download`,
    {
      params: revision ? { revision } : undefined,
      responseType: "blob",
    },
  );
}

export async function listProjectOptions(): Promise<ProjectOption[]> {
  const rows = await apiClient.get<Array<{ id: string; name: string }>>(
    "/projects",
    { params: { limit: 100 } },
  );
  return rows.map(({ id, name }) => ({ id, name }));
}
