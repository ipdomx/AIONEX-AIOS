import { apiClient } from "@/lib/api-client";

export type MobileArtifact = {
  id: string;
  artifact_type: string;
  filename: string;
  media_type: string;
  checksum: string;
  size_bytes: number;
  signed: boolean;
  signature_metadata: Record<string, unknown>;
  status: string;
  created_at: string;
};

export type MobileValidation = {
  id: string;
  operation: string;
  status: string;
  evidence: Record<string, unknown>;
  completed_at: string | null;
  created_at: string;
};

export type MobileRelease = {
  id: string;
  platform: "pwa" | "android" | "ios";
  version: string;
  build_number: number;
  channel: string;
  status: string;
  signing_status: string;
  publication_status: string;
  source_commit: string;
  manifest_checksum: string;
  metadata: Record<string, unknown>;
  built_at: string | null;
  validated_at: string | null;
  artifacts: MobileArtifact[];
  validations: MobileValidation[];
};

export async function listMobileReleases(
  signal?: AbortSignal,
): Promise<MobileRelease[]> {
  return apiClient.get<MobileRelease[]>("/owner/mobile/releases", { signal });
}

export async function downloadMobileArtifact(
  releaseId: string,
  artifactId: string,
): Promise<Blob> {
  return apiClient.get<Blob>(
    `/owner/mobile/releases/${encodeURIComponent(releaseId)}/artifacts/${encodeURIComponent(artifactId)}/download`,
    { responseType: "blob" },
  );
}

export type MobileReadiness = {
  platforms: Record<
    "pwa" | "android" | "ios",
    {
      registered: boolean;
      status: string;
      version: string | null;
      signing_status: string;
      publication_status: string;
      validations_passed: boolean;
    }
  >;
  pwa_host_deployment_deferred: boolean;
  ai_vip_dns_changed: boolean;
  store_publication_automatic: boolean;
  provider_activation_batch: string;
};

export async function getMobileReadiness(
  signal?: AbortSignal,
): Promise<MobileReadiness> {
  return apiClient.get<MobileReadiness>("/owner/mobile/readiness", { signal });
}

export async function getMobileRelease(
  releaseId: string,
  signal?: AbortSignal,
): Promise<MobileRelease> {
  return apiClient.get<MobileRelease>(
    `/owner/mobile/releases/${encodeURIComponent(releaseId)}`,
    { signal },
  );
}
