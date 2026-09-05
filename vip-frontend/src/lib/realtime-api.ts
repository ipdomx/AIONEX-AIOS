import { jsonRequest, request } from "@/lib/api";

export type RealtimeReadiness = {
  enabled: boolean;
  provider: string;
  signaling_url: string | null;
  turn_host_configured: boolean;
  turn_port: number | null;
  static_provider_credentials_returned: false;
  short_lived_participant_credentials: boolean;
  recording_provider: string;
};

export type RealtimeRoom = {
  id: string;
  room_key: string;
  workspace_id: string | null;
  project_id: string | null;
  created_by_id: string;
  room_type: string;
  media_mode: string;
  status: string;
  provider: string;
  max_participants: number;
  participant_count: number;
  allow_screen_share: boolean;
  recording_policy: string;
  opened_at: string | null;
  closed_at: string | null;
  created_at: string;
  provider_room_identifier_returned: false;
};

export type RealtimeJoinSession = {
  token: string;
  expires_at: string;
  server_url: string;
  ice_servers: RTCIceServer[];
  provider: string;
};

export type RealtimeJoinResult = {
  room: RealtimeRoom;
  participant_id: string;
  session: RealtimeJoinSession;
  admission_grant_returned: false;
};

export type RealtimeRecording = {
  id: string;
  room_id: string;
  requested_by_id: string;
  title: string;
  status: string;
  provider: string;
  output_format: string;
  media_type: string;
  consent_version: string;
  required_consent_count: number;
  consented_count: number;
  retention_until: string;
  output_checksum_sha256: string | null;
  output_size_bytes: number | null;
  output_duration_ms: number | null;
  studio_job_id: string | null;
  studio_asset_id: string | null;
  error_code: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  provider_egress_identifier_returned: false;
  raw_consent_material_returned: false;
};

export function realtimeReadiness(): Promise<RealtimeReadiness> {
  return request("/realtime/media/readiness");
}

export function listRealtimeRooms(): Promise<RealtimeRoom[]> {
  return request("/realtime/media/rooms?limit=100");
}

export function createRealtimeRoom(payload: {
  room_key: string;
  idempotency_key: string;
  room_type?: "meeting" | "collaboration" | "support" | "studio";
  media_mode?: "audio" | "video" | "audio_video";
  max_participants?: number;
  allow_screen_share?: boolean;
}): Promise<RealtimeRoom> {
  return jsonRequest("/realtime/media/rooms", "POST", payload);
}

export function joinRealtimeRoom(
  roomId: string,
  payload: {
    idempotency_key: string;
    can_publish: boolean;
    can_subscribe: boolean;
    can_screen_share: boolean;
  },
): Promise<RealtimeJoinResult> {
  return jsonRequest(
    `/realtime/media/rooms/${encodeURIComponent(roomId)}/join`,
    "POST",
    payload,
  );
}

export function leaveRealtimeRoom(roomId: string): Promise<{ room_id: string; left: boolean }> {
  return jsonRequest(
    `/realtime/media/rooms/${encodeURIComponent(roomId)}/leave`,
    "POST",
    {},
  );
}

export function closeRealtimeRoom(roomId: string): Promise<RealtimeRoom> {
  return jsonRequest(
    `/realtime/media/rooms/${encodeURIComponent(roomId)}/close`,
    "POST",
    {},
  );
}

export function listRealtimeRecordings(roomId: string): Promise<RealtimeRecording[]> {
  return request(`/realtime/media/rooms/${encodeURIComponent(roomId)}/recordings`);
}

export function requestRealtimeRecording(
  roomId: string,
  payload: {
    title: string;
    idempotency_key: string;
    consent_version: string;
    retention_days: number;
  },
): Promise<RealtimeRecording> {
  return jsonRequest(
    `/realtime/media/rooms/${encodeURIComponent(roomId)}/recordings`,
    "POST",
    payload,
  );
}

export function setRealtimeRecordingConsent(
  recordingId: string,
  consented: boolean,
): Promise<RealtimeRecording> {
  return jsonRequest(
    `/realtime/media/recordings/${encodeURIComponent(recordingId)}/consent`,
    "POST",
    { consented },
  );
}

export function getRealtimeRecording(recordingId: string): Promise<RealtimeRecording> {
  return request(`/realtime/media/recordings/${encodeURIComponent(recordingId)}`);
}

export function stopRealtimeRecording(recordingId: string): Promise<RealtimeRecording> {
  return jsonRequest(
    `/realtime/media/recordings/${encodeURIComponent(recordingId)}/stop`,
    "POST",
    {},
  );
}
