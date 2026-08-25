import {
  downloadAuthenticated,
  jsonRequest,
  request,
} from "@/lib/api";


export type StudioCapabilityPolicy = {
  enabled: boolean;
  eligible_plans: string[];
  daily_job_limit: number;
  max_concurrent_jobs: number;
  max_attempts: number;
  max_cost_usd: number;
  provider_mode: string;
  moderation_mode: string;
  version: number;
};

export type StudioHubCapability = {
  capability_id: string;
  title: string;
  category: string;
  launch_surface: string;
  departments: string[];
  phase36_capability_ids: string[];
  supported_plans: string[];
  required_permissions: string[];
  runtime_launchable: boolean;
  activation_reason: string | null;
  maturities: string[];
  external_gates: string[];
  policy: StudioCapabilityPolicy;
  policy_source: string;
  available: boolean;
  availability_reason: string;
  organization_plan: string;
};

export type StudioHubSnapshot = {
  generated_at: string;
  provider_mode: string;
  capabilities: StudioHubCapability[];
  jobs: Record<string, number>;
  active_assets: number;
};



export type StudioSectorPack = {
  key: string;
  title: string;
  objective: string;
  audience: string;
  roles: string[];
  entity_count: number;
  workflow_count: number;
  workflows: string[];
  safety_boundaries: string[];
  external_gates: string[];
  domain_blueprint: Record<string, unknown>;
};

export type StudioSectorCatalog = {
  capability: StudioHubCapability;
  packs: StudioSectorPack[];
  custom_composer: {
    capability_id: string;
    schema_version: number;
    launch_surface: string;
    description: string;
  };
};

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
  provider_mode: string;
  provider: string | null;
  model: string | null;
  status: string;
  progress: number;
  safety_status: string;
  safety_findings: Array<Record<string, unknown>>;
  request_metadata: Record<string, unknown>;
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
  media_type: string;
  checksum: string;
  size_bytes: number;
  change_note: string | null;
  status: string;
  created_at: string;
};

export function getStudioHub(): Promise<StudioHubSnapshot> {
  return request("/studio/hub");
}


export function getStudioSectorPacks(): Promise<StudioSectorCatalog> {
  return request("/studio/sector-packs");
}

export async function getStudioDepartments(): Promise<{
  departments: StudioDepartment[];
  count: number;
  provider_mode: string;
  provider_activation_batch: string;
}> {
  return request("/studio/departments");
}

export function createStudioJob(payload: {
  department: string;
  title: string;
  brief: string;
  language: string;
  style: string;
  target?: string | null;
  programming_language?: string | null;
  project_id?: string | null;
}): Promise<StudioJob> {
  return jsonRequest<StudioJob>("/studio/jobs", "POST", payload);
}

export function listStudioJobs(): Promise<StudioJob[]> {
  return request("/studio/jobs?limit=100");
}

export function retryStudioJob(jobId: string): Promise<StudioJob> {
  return jsonRequest<StudioJob>(
    `/studio/jobs/${encodeURIComponent(jobId)}/retry`,
    "POST",
    {},
  );
}

export function cancelStudioJob(jobId: string): Promise<StudioJob> {
  return jsonRequest<StudioJob>(
    `/studio/jobs/${encodeURIComponent(jobId)}/cancel`,
    "POST",
    {},
  );
}

export function listStudioAssets(): Promise<StudioAsset[]> {
  return request("/studio/assets?limit=100");
}

export function listStudioRevisions(assetId: string): Promise<StudioRevision[]> {
  return request(
    `/studio/assets/${encodeURIComponent(assetId)}/revisions`,
  );
}

export function createStudioRevision(
  assetId: string,
  payload: {
    brief: string;
    change_note: string;
    title?: string | null;
    language?: string | null;
    style?: string | null;
    target?: string | null;
    programming_language?: string | null;
  },
): Promise<StudioJob> {
  return jsonRequest<StudioJob>(
    `/studio/assets/${encodeURIComponent(assetId)}/revisions`,
    "POST",
    payload,
  );
}

export async function attachStudioAsset(
  assetId: string,
  projectId: string,
): Promise<void> {
  await jsonRequest(
    `/studio/assets/${encodeURIComponent(assetId)}/attach`,
    "POST",
    { project_id: projectId },
  );
}

export function downloadStudioAsset(
  assetId: string,
): Promise<{ blob: Blob; filename: string }> {
  return downloadAuthenticated(
    `/studio/assets/${encodeURIComponent(assetId)}/download`,
  );
}
