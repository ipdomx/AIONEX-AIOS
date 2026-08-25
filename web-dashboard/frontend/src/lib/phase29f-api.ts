import { apiClient } from "@/lib/api-client";

export type ProjectRecord = {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  status: string;
  priority: string;
  risk: string;
  review_status: string;
  progress: number;
  workspace_id: string;
  workspace: string;
  organization_id: string;
  organization: string;
  owner_id: string;
  owner: string;
  team_count: number;
  task_count: number;
  version: number;
  tags: string[];
  created_at: string;
  updated_at: string;
};

export type ProjectEvent = {
  id: string;
  project_id: string;
  actor_id: string | null;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  summary: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

export type TaskRecord = {
  id: string;
  title: string;
  description?: string | null;
  status: string;
  priority: string;
  review_status: string;
  rework_count: number;
  assignee_id?: string | null;
  assignee?: string | null;
  project_id?: string | null;
  project?: string | null;
  workspace_id?: string | null;
  organization_id: string;
  due_date?: string | null;
  tags: string[];
  comments: TaskComment[];
  version: number;
  created_at: string;
  updated_at: string;
};

export type TaskComment = {
  id: string;
  task_id: string;
  author_id: string | null;
  workforce_member_id: string | null;
  visibility: "project" | "internal";
  body: string;
  attachments: Array<Record<string, unknown>>;
  created_at: string;
};

export type WorkflowRecord = {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  organization_id: string;
  workspace_id?: string | null;
  project_id?: string | null;
  trigger: string;
  steps: Array<Record<string, unknown>>;
  run_count: number;
  last_run_at?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
};

export type WorkflowRun = {
  id: string;
  workflow_id: string;
  project_id?: string | null;
  requested_by_id: string;
  status: string;
  current_step: number;
  attempt_count: number;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  evidence: Array<Record<string, unknown>>;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export type ReportRecord = {
  id: string;
  name: string;
  type: string;
  status: string;
  organization_id: string;
  workspace_id?: string | null;
  project_id?: string | null;
  generated_by?: string | null;
  summary?: string | null;
  metrics: Record<string, number>;
  format: string;
  checksum?: string | null;
  size_bytes?: number | null;
  version: number;
  archived_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkforceMember = {
  id: string;
  organization_id: string;
  user_id?: string | null;
  manager_id?: string | null;
  worker_key: string;
  kind: "human" | "digital";
  name: string;
  role: string;
  department: string;
  ministry?: string | null;
  grade: number;
  status: string;
  skills: string[];
  certifications: string[];
  restrictions: string[];
  warnings: string[];
  provider_neutral: boolean;
  metadata: Record<string, unknown>;
  version: number;
  performance?: number | null;
  reliability?: number | null;
  collaboration?: number | null;
  operational_health?: number | null;
  trust?: number | null;
  learning?: number | null;
  recommendation?: string | null;
  success_count: number;
  failure_count: number;
  last_evaluated_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkforceAssignment = {
  id: string;
  organization_id: string;
  project_id: string;
  task_id?: string | null;
  worker_id: string;
  reviewer_id?: string | null;
  title: string;
  required_skills: string[];
  acceptance_criteria: string[];
  status: string;
  priority: number;
  risk: string;
  evidence: Record<string, unknown>;
  defects: string[];
  attempts: number;
  completeness: number;
  version: number;
  created_at: string;
  updated_at: string;
};

export type WorkforceIncident = {
  id: string;
  worker_id: string;
  assignment_id?: string | null;
  severity: string;
  category: string;
  description: string;
  status: string;
  restrictions_applied: string[];
  created_at: string;
  updated_at: string;
};

export type AcademyCourse = {
  id: string;
  code: string;
  title: string;
  description?: string | null;
  competencies: string[];
  passing_score: number;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
};

export type AcademyCoursePackage = {
  id: string;
  course_id: string;
  status: string;
  version: number;
  lesson_count: number;
  request: { domain?: string; audience?: string; locales?: string[] };
  curriculum: {
    learning_outcomes?: string[];
    lessons?: Array<{ key: string }>;
  };
  citations: Array<Record<string, unknown>>;
  review: Record<string, unknown>;
  archive_sha256?: string | null;
  manifest_sha256?: string | null;
  archive_bytes: number;
  download_ready: boolean;
  site_ready: boolean;
  error_code?: string | null;
  completed_at?: string | null;
  reviewed_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type AcademyEnrollment = {
  id: string;
  course_id: string;
  worker_id: string;
  status: string;
  attempts: number;
  due_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type AcademyCertification = {
  id: string;
  worker_id: string;
  course_id: string;
  assessment_id: string;
  code: string;
  status: string;
  issued_at: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  metadata: Record<string, unknown>;
};

export type KnowledgeItem = {
  id: string;
  organization_id: string;
  workspace_id?: string | null;
  project_id?: string | null;
  worker_id?: string | null;
  scope_type: string;
  scope_id: string;
  namespace: string;
  subject: string;
  content: Record<string, unknown>;
  content_text: string;
  confidence: number;
  status: string;
  checksum: string;
  tags: string[];
  version: number;
  verified_at?: string | null;
  created_at: string;
  updated_at: string;
  provenance: Array<{
    id: string;
    source: string;
    source_type: string;
    author?: string | null;
    uri?: string | null;
    source_quality: number;
    direct_evidence: boolean;
    collected_at: string;
  }>;
};

export type ScopedMemory = {
  id: string;
  scope_type: string;
  scope_id: string;
  key: string;
  value: Record<string, unknown>;
  summary?: string | null;
  confidence: number;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
};

export type LearningEvent = {
  id: string;
  project_id?: string | null;
  worker_id?: string | null;
  assignment_id?: string | null;
  action: string;
  context_fingerprint: string;
  outcome: string;
  evidence: string[];
  strategy?: string | null;
  lesson?: string | null;
  status: string;
  verified_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type Lesson = {
  id: string;
  project_id?: string | null;
  worker_id?: string | null;
  source_event_id?: string | null;
  title: string;
  lesson: string;
  confidence: number;
  status: string;
  tags: string[];
  version: number;
  promoted_at?: string | null;
  created_at: string;
  updated_at: string;
};

export const phase29fApi = {
  listProjects(params?: Record<string, string | number | undefined>) {
    return apiClient.get<ProjectRecord[]>("/projects", { params });
  },
  listProjectHistory(projectId: string) {
    return apiClient.get<ProjectEvent[]>(
      `/projects/${encodeURIComponent(projectId)}/history`,
    );
  },
  transitionProject(projectId: string, action: string, reason = "") {
    return apiClient.post<ProjectRecord>(
      `/projects/${encodeURIComponent(projectId)}/transition`,
      { action, reason },
    );
  },
  listTasks(params?: Record<string, string | number | undefined>) {
    return apiClient.get<TaskRecord[]>("/tasks", { params });
  },
  createTask(payload: Record<string, unknown>) {
    return apiClient.post<TaskRecord>("/tasks", payload);
  },
  transitionTask(taskId: string, action: string, reason = "") {
    return apiClient.post<TaskRecord>(
      `/tasks/${encodeURIComponent(taskId)}/transition`,
      { action, reason },
    );
  },
  listTaskComments(taskId: string) {
    return apiClient.get<TaskComment[]>(
      `/tasks/${encodeURIComponent(taskId)}/comments`,
    );
  },
  addTaskComment(taskId: string, body: string) {
    return apiClient.post<TaskComment>(
      `/tasks/${encodeURIComponent(taskId)}/comments`,
      { body, visibility: "project" },
    );
  },
  listWorkflows(params?: Record<string, string | number | undefined>) {
    return apiClient.get<WorkflowRecord[]>("/workflows", { params });
  },
  createWorkflow(payload: Record<string, unknown>) {
    return apiClient.post<WorkflowRecord>("/workflows", payload);
  },
  runWorkflow(workflowId: string, input: Record<string, unknown> = {}) {
    return apiClient.post<{
      status: string;
      run_status: string;
      workflow: WorkflowRecord;
      run: WorkflowRun;
    }>(`/workflows/${encodeURIComponent(workflowId)}/run`, { input });
  },
  listWorkflowRuns(workflowId: string) {
    return apiClient.get<WorkflowRun[]>(
      `/workflows/${encodeURIComponent(workflowId)}/runs`,
    );
  },
  listReports(params?: Record<string, string | number | undefined>) {
    return apiClient.get<ReportRecord[]>("/reports", { params });
  },
  createReport(payload: Record<string, unknown>) {
    return apiClient.post<ReportRecord>("/reports", payload);
  },
  generateReport(reportId: string) {
    return apiClient.post<ReportRecord>(
      `/reports/${encodeURIComponent(reportId)}/generate`,
    );
  },
  downloadReport(reportId: string) {
    return apiClient.request<Blob>({
      method: "GET",
      url: `/reports/${encodeURIComponent(reportId)}/download`,
      responseType: "blob",
    });
  },
  archiveReport(reportId: string) {
    return apiClient.post<ReportRecord>(
      `/reports/${encodeURIComponent(reportId)}/archive`,
    );
  },
  listWorkforceMembers(params?: Record<string, string | number | undefined>) {
    return apiClient.get<WorkforceMember[]>("/workforce/members", { params });
  },
  createDigitalMember(payload: Record<string, unknown>) {
    return apiClient.post<WorkforceMember>("/workforce/members", payload);
  },
  transitionMember(memberId: string, payload: Record<string, unknown>) {
    return apiClient.patch<WorkforceMember>(
      `/workforce/members/${encodeURIComponent(memberId)}/lifecycle`,
      payload,
    );
  },
  listAssignments(params?: Record<string, string | number | undefined>) {
    return apiClient.get<WorkforceAssignment[]>("/workforce/assignments", {
      params,
    });
  },
  createAssignment(payload: Record<string, unknown>) {
    return apiClient.post<WorkforceAssignment>(
      "/workforce/assignments",
      payload,
    );
  },
  transitionAssignment(assignmentId: string, payload: Record<string, unknown>) {
    return apiClient.post<WorkforceAssignment>(
      `/workforce/assignments/${encodeURIComponent(assignmentId)}/transition`,
      payload,
    );
  },
  evaluateMember(memberId: string) {
    return apiClient.post<Record<string, unknown>>(
      `/workforce/members/${encodeURIComponent(memberId)}/health`,
      {},
    );
  },
  listWorkforceIncidents(params?: Record<string, string | number | undefined>) {
    return apiClient.get<WorkforceIncident[]>("/workforce/incidents", {
      params,
    });
  },
  createWorkforceIncident(payload: Record<string, unknown>) {
    return apiClient.post<WorkforceIncident>("/workforce/incidents", payload);
  },
  resolveWorkforceIncident(incidentId: string, note: string) {
    return apiClient.post<WorkforceIncident>(
      `/workforce/incidents/${encodeURIComponent(incidentId)}/resolve`,
      { note },
    );
  },

  listCoursePackages(courseId: string) {
    return apiClient.get<AcademyCoursePackage[]>(
      `/academy/courses/${encodeURIComponent(courseId)}/packages`,
    );
  },
  createCoursePackage(courseId: string, payload: Record<string, unknown>) {
    return apiClient.post<AcademyCoursePackage>(
      `/academy/courses/${encodeURIComponent(courseId)}/packages`,
      payload,
    );
  },
  reviewCoursePackage(packageId: string, approved: boolean, notes = "") {
    return apiClient.post<AcademyCoursePackage>(
      `/academy/packages/${encodeURIComponent(packageId)}/review`,
      { approved, notes },
    );
  },
  listCourses() {
    return apiClient.get<AcademyCourse[]>("/academy/courses");
  },
  createCourse(payload: Record<string, unknown>) {
    return apiClient.post<AcademyCourse>("/academy/courses", payload);
  },
  enroll(courseId: string, workerId: string) {
    return apiClient.post<AcademyEnrollment>(
      `/academy/courses/${encodeURIComponent(courseId)}/enroll`,
      { worker_id: workerId },
    );
  },
  listEnrollments(params?: Record<string, string | number | undefined>) {
    return apiClient.get<AcademyEnrollment[]>("/academy/enrollments", {
      params,
    });
  },
  assessEnrollment(enrollmentId: string, score: number) {
    return apiClient.post<{
      assessment: Record<string, unknown>;
      certification: AcademyCertification | null;
    }>(`/academy/enrollments/${encodeURIComponent(enrollmentId)}/assess`, {
      score,
      evidence: { source: "owner-dashboard" },
    });
  },
  listCertifications(params?: Record<string, string | number | undefined>) {
    return apiClient.get<AcademyCertification[]>("/academy/certifications", {
      params,
    });
  },
  listKnowledge(
    params?: Record<string, string | number | boolean | undefined>,
  ) {
    return apiClient.get<KnowledgeItem[]>("/knowledge/items", { params });
  },
  createKnowledge(payload: Record<string, unknown>) {
    return apiClient.post<KnowledgeItem>("/knowledge/items", payload);
  },
  verifyKnowledge(itemId: string, accepted: boolean, confidence?: number) {
    return apiClient.post<KnowledgeItem>(
      `/knowledge/items/${encodeURIComponent(itemId)}/verify`,
      { accepted, confidence, note: "Dashboard verification" },
    );
  },
  searchKnowledge(query: string) {
    return apiClient.get<KnowledgeItem[]>("/knowledge/search", {
      params: { q: query, limit: 100 },
    });
  },
  listMemories() {
    return apiClient.get<ScopedMemory[]>("/knowledge/memories");
  },
  upsertMemory(payload: Record<string, unknown>) {
    return apiClient.put<ScopedMemory>("/knowledge/memories", payload);
  },
  listLearningEvents() {
    return apiClient.get<LearningEvent[]>("/knowledge/learning-events");
  },
  createLearningEvent(payload: Record<string, unknown>) {
    return apiClient.post<LearningEvent>("/knowledge/learning-events", payload);
  },
  verifyLearningEvent(eventId: string, accepted: boolean) {
    return apiClient.post<LearningEvent>(
      `/knowledge/learning-events/${encodeURIComponent(eventId)}/verify`,
      { accepted, note: "Dashboard verification" },
    );
  },
  promoteLesson(eventId: string, title: string, lesson?: string) {
    return apiClient.post<Lesson>(
      `/knowledge/learning-events/${encodeURIComponent(eventId)}/promote`,
      { title, lesson, confidence: 0.8, tags: ["phase29f"] },
    );
  },
  listLessons() {
    return apiClient.get<Lesson[]>("/knowledge/lessons");
  },
};
