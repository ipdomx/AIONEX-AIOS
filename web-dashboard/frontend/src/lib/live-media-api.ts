import { apiClient } from "@/lib/api-client";

export type LiveMediaKind =
  | "image"
  | "video"
  | "speech"
  | "transcript"
  | "dubbing"
  | "music"
  | "song";

export type LiveMediaCapabilityState = {
  ready: boolean;
  worker_live: boolean;
  requires_provider_preflight?: boolean;
  secondary_account_used?: boolean;
};

export type LiveMediaCapabilities = {
  schema: string;
  image: LiveMediaCapabilityState;
  video: LiveMediaCapabilityState;
  speech: LiveMediaCapabilityState;
  transcript: LiveMediaCapabilityState;
  dubbing: LiveMediaCapabilityState;
  music: LiveMediaCapabilityState;
  open_song: LiveMediaCapabilityState;
  credentials_returned: false;
};

export type LiveMediaJob = {
  kind: LiveMediaKind;
  id: string;
  graph_id?: string | null;
  scene_key?: string;
  status: string;
  provider?: string | null;
  model?: string | null;
  attempts: number;
  max_attempts: number;
  actual_cost_usd?: number | null;
  created_at: string;
  error_code?: string | null;
};

export type LiveMediaJobList = {
  jobs: LiveMediaJob[];
  credential_returned: false;
  raw_provider_job_id_returned: false;
};

export type LiveMediaResult = Record<string, unknown> & {
  kind: LiveMediaKind;
  status?: string;
  execution_id?: string;
  id?: string;
  graph_id?: string;
};

export async function getLiveMediaCapabilities(): Promise<LiveMediaCapabilities> {
  return apiClient.get<LiveMediaCapabilities>("/studio/live-media/capabilities");
}

export async function listLiveMediaJobs(): Promise<LiveMediaJobList> {
  return apiClient.get<LiveMediaJobList>("/studio/live-media/jobs");
}

export async function createLiveMedia(
  kind: LiveMediaKind,
  payload: Record<string, unknown>,
): Promise<LiveMediaResult> {
  return apiClient.post<LiveMediaResult>(`/studio/live-media/${kind}`, payload);
}

export async function getLiveMediaStatus(
  kind: LiveMediaKind,
  id: string,
): Promise<Record<string, unknown>> {
  const encoded = encodeURIComponent(id);
  return apiClient.get<Record<string, unknown>>(
    `/studio/live-media/${kind}/${encoded}`,
  );
}
