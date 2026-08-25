import {
  downloadAuthenticated,
  jsonRequest,
  request,
} from "@/lib/api";

export type AcademyCourse = {
  id: string;
  organization_id: string;
  code: string;
  title: string;
  description: string | null;
  competencies: string[];
  passing_score: number;
  status: string;
  version: number;
  created_by_id: string;
  created_at: string;
  updated_at: string;
};

export type AcademyCoursePackage = {
  id: string;
  course_id: string;
  status: "queued" | "building" | "review_pending" | "approved" | "rejected" | "failed" | string;
  version: number;
  lesson_count: number;
  request: Record<string, unknown>;
  curriculum: Record<string, unknown> | null;
  citations: Array<Record<string, unknown>>;
  review: Record<string, unknown>;
  archive_sha256: string | null;
  manifest_sha256: string | null;
  archive_bytes: number | null;
  download_ready: boolean;
  site_ready: boolean;
  error_code: string | null;
  completed_at: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
};

export function listAcademyCourses(): Promise<AcademyCourse[]> {
  return request("/academy/courses?limit=200");
}

export function createAcademyCourse(payload: {
  code: string;
  title: string;
  description?: string | null;
  competencies?: string[];
  passing_score?: number;
}): Promise<AcademyCourse> {
  return jsonRequest<AcademyCourse>("/academy/courses", "POST", payload);
}

export function listAcademyCoursePackages(
  courseId: string,
): Promise<AcademyCoursePackage[]> {
  return request(
    `/academy/courses/${encodeURIComponent(courseId)}/packages`,
  );
}

export function createAcademyCoursePackage(
  courseId: string,
  payload: {
    idempotency_key: string;
    domain: string;
    audience: string;
    locales: string[];
    module_count: number;
    lessons_per_module: number;
    citations?: Array<{
      citation_id: string;
      title: string;
      uri: string;
      author?: string | null;
    }>;
  },
): Promise<AcademyCoursePackage> {
  return jsonRequest<AcademyCoursePackage>(
    `/academy/courses/${encodeURIComponent(courseId)}/packages`,
    "POST",
    payload,
  );
}

export function getAcademyCoursePackage(
  packageId: string,
): Promise<AcademyCoursePackage> {
  return request(`/academy/packages/${encodeURIComponent(packageId)}`);
}

export function reviewAcademyCoursePackage(
  packageId: string,
  payload: { approved: boolean; notes: string },
): Promise<AcademyCoursePackage> {
  return jsonRequest<AcademyCoursePackage>(
    `/academy/packages/${encodeURIComponent(packageId)}/review`,
    "POST",
    payload,
  );
}

export function downloadAcademyCoursePackage(
  packageId: string,
): Promise<{ blob: Blob; filename: string }> {
  return downloadAuthenticated(
    `/academy/packages/${encodeURIComponent(packageId)}/download`,
  );
}
