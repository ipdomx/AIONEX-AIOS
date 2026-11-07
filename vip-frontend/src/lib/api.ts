import type {
  AccountSession,
  AdAccountLink,
  AdsAccess,
  AdsAvailableAccount,
  AdsCampaign,
  AdsCampaignInput,
  AdsConnection,
  AdsDashboard,
  AdsRecommendationRun,
  AdsUsage,
  AccountSettings,
  BillingCatalog,
  BillingCheckout,
  BillingPaymentMethod,
  BillingSummary,
  BillingSubscriptionSummary,
  CreateProjectPayload,
  FirebasePhoneConfiguration,
  FirebasePhoneReadiness,
  FirebaseSocialConfiguration,
  FreeRegistrationPayload,
  FreeTierPublicPolicy,
  FreeTierStatus,
  LoginAttempt,
  LoginResponse,
  MFASetup,
  MFAStatus,
  PasskeyCeremonyOptions,
  PasskeyConfiguration,
  PasskeyCredentialSummary,
  CommunicationChannelReadiness,
  CommunicationEndpoint,
  NotificationPreference,
  PaidCampaign,
  PaidCampaignPreparationInput,
  PaidCampaignPreparationResult,
  PaidCampaignReadiness,
  Phase36ProgramSnapshot,
  PortalNotification,
  SupportTicket,
  SupportTicketMessage,
  UserTelegramChallenge,
  UserTelegramStatus,
  SecurityFindingRecord,
  SecurityLabAccess,
  SecurityRemediationRecord,
  SecurityScanRecord,
  SecurityScanReport,
  SecurityTargetRecord,
  SecurityTool,
  SecurityProfile,
  SecurityVerificationInstructions,
  SecurityVerificationMethod,
  Project,
  ProjectExecution,
  ThreeDAccess,
  ThreeDArtifactLinks,
  ThreeDGenerationJob,
  RegistrationTelemetry,
  SocialRegistrationPreparation,
  SocialAccount,
  SocialAsset,
  SocialConnectResult,
  SocialConnection,
  SocialDisconnectResult,
  SocialProvider,
  SocialAiAssistResult,
  SocialInboxConversation,
  SocialInboxReadiness,
  SocialInboxAccountReadiness,
  SocialInboxSuggestion,
  SocialInboxThread,
  MetaDataDeletionStatus,
  SocialMediaItem,
  SocialPost,
  SocialPostInput,
  SocialValidationReport,
  User,
  Workspace,
} from "@/types";
import {
  createRefreshGate,
  parseRetryAfterMs,
  RefreshFailure,
} from "@/lib/auth-refresh-gate";

const API_ROOT = (process.env.NEXT_PUBLIC_API_URL || "/api/v1").replace(
  /\/$/,
  "",
);

const STORAGE_KEYS = {
  access: "aionex.access_token",
  refresh: "aionex.refresh_token",
  user: "aionex.user",
} as const;

const LEGACY_STORAGE_KEYS = {
  access: "aionex.vip.access-token",
  refresh: "aionex.vip.refresh-token",
  user: "aionex.vip.user",
} as const;

function browserStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readStorage(key: string): string | null {
  try {
    const storage = browserStorage();
    const current = storage?.getItem(key) || null;
    if (current || !storage) return current;
    const legacyEntry = Object.entries(STORAGE_KEYS).find(
      ([, value]) => value === key,
    );
    if (!legacyEntry) return null;
    const legacyKey =
      LEGACY_STORAGE_KEYS[legacyEntry[0] as keyof typeof LEGACY_STORAGE_KEYS];
    const legacyValue = storage.getItem(legacyKey);
    if (!legacyValue) return null;
    storage.setItem(key, legacyValue);
    storage.removeItem(legacyKey);
    return legacyValue;
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    browserStorage()?.setItem(key, value);
  } catch {
    // Storage can be blocked by browser privacy settings. The request still
    // succeeds, but the user will need to sign in again after navigation.
  }
}

function removeStorage(key: string): void {
  try {
    browserStorage()?.removeItem(key);
  } catch {
    // Ignore unavailable browser storage.
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: unknown;

  constructor(
    status: number,
    message: string,
    code: string | null,
    detail: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function storeSession(session: LoginResponse): LoginResponse {
  if (session.user.role === "Super Owner") {
    clearSession();
    throw new Error("Session is not available on this portal");
  }
  removeStorage(STORAGE_KEYS.access);
  removeStorage(STORAGE_KEYS.refresh);
  removeStorage(LEGACY_STORAGE_KEYS.access);
  removeStorage(LEGACY_STORAGE_KEYS.refresh);
  writeStorage(STORAGE_KEYS.user, JSON.stringify(session.user));
  // A fresh session (login or successful refresh) lifts any refresh backoff.
  refreshGate.reset();
  return session;
}

export function clearSession(): void {
  for (const key of [
    ...Object.values(STORAGE_KEYS),
    ...Object.values(LEGACY_STORAGE_KEYS),
  ]) {
    removeStorage(key);
  }
}

export function hasStoredSession(): boolean {
  return Boolean(readStorage(STORAGE_KEYS.user));
}

export function storedUser(): User | null {
  const value = readStorage(STORAGE_KEYS.user);
  if (!value) return null;
  try {
    return JSON.parse(value) as User;
  } catch {
    clearSession();
    return null;
  }
}

interface ApiRequestOptions extends RequestInit {
  auth?: boolean;
  retry?: boolean;
}

async function responsePayload(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function apiError(response: Response, payload: unknown): ApiError {
  const object =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : null;
  const detail = object?.detail ?? payload;
  const detailObject =
    detail && typeof detail === "object"
      ? (detail as Record<string, unknown>)
      : null;
  const codeValue = detailObject?.code ?? object?.code;
  const messageValue =
    detailObject?.message ??
    (typeof detail === "string" ? detail : null) ??
    object?.message ??
    `Request failed with status ${response.status}`;
  return new ApiError(
    response.status,
    String(messageValue),
    typeof codeValue === "string" ? codeValue : null,
    detail,
  );
}

async function performRefresh(): Promise<LoginResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_ROOT}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({}),
    });
  } catch {
    // Network failure or a CORS-blocked response (for example an nginx 429
    // without CORS headers). Never surface it as an unhandled rejection.
    throw new RefreshFailure(null);
  }
  let payload: unknown = null;
  try {
    payload = await responsePayload(response);
  } catch {
    payload = null;
  }
  if (!response.ok || !payload || typeof payload !== "object") {
    throw new RefreshFailure(
      response.ok ? null : response.status,
      parseRetryAfterMs(response.headers.get("Retry-After")),
    );
  }
  return storeSession(payload as LoginResponse);
}

// One shared refresh for the whole page: anonymous visitors never refresh,
// concurrent 401s share one request and failures back off instead of looping.
const refreshGate = createRefreshGate<LoginResponse>({
  hasSessionHint: hasStoredSession,
  clearSession,
});

function refreshSession(): Promise<LoginResponse | null> {
  return refreshGate.run(performRefresh);
}

export async function request<T>(
  path: string,
  { auth = true, retry = true, ...init }: ApiRequestOptions = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  const response = await fetch(`${API_ROOT}${path}`, {
    credentials: "include",
    ...init,
    headers,
  });
  if (response.status === 401 && auth && retry) {
    // Never refresh recursively: the replay runs with retry disabled, and a
    // failed or skipped refresh surfaces the original 401 below.
    if (await refreshSession()) {
      return request<T>(path, { ...init, auth, retry: false });
    }
  }

  const payload = await responsePayload(response);
  if (!response.ok) throw apiError(response, payload);
  return payload as T;
}

export async function downloadAuthenticated(
  path: string,
  retry = true,
): Promise<{ blob: Blob; filename: string }> {
  const headers = new Headers({ Accept: "application/zip" });
  const response = await fetch(`${API_ROOT}${path}`, {
    credentials: "include",
    headers,
  });
  if (response.status === 401 && retry && (await refreshSession())) {
    return downloadAuthenticated(path, false);
  }
  if (!response.ok) {
    const payload = await responsePayload(response);
    throw apiError(response, payload);
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return {
    blob: await response.blob(),
    filename: match?.[1] || "aionex-project-delivery.zip",
  };
}

export async function downloadAuthenticatedBlob(
  path: string,
  retry = true,
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_ROOT}${path}`, {
    credentials: "include",
    headers: { Accept: "*/*" },
  });
  if (response.status === 401 && retry && (await refreshSession())) {
    return downloadAuthenticatedBlob(path, false);
  }
  if (!response.ok) {
    const payload = await responsePayload(response);
    throw apiError(response, payload);
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const basic = disposition.match(/filename="?([^";]+)"?/i);
  return {
    blob: await response.blob(),
    filename: decodeURIComponent(utf8?.[1] || basic?.[1] || "aionex-identity-media-output"),
  };
}

export function jsonRequest<T>(
  path: string,
  method: "POST" | "PATCH" | "PUT" | "DELETE",
  body?: unknown,
  options: ApiRequestOptions = {},
): Promise<T> {
  return request<T>(path, {
    ...options,
    method,
    headers: { "Content-Type": "application/json", ...options.headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export async function login(
  email: string,
  password: string,
): Promise<LoginAttempt> {
  const body = new URLSearchParams({ username: email.trim(), password });
  const result = await request<LoginAttempt>("/auth/login", {
    method: "POST",
    auth: false,
    retry: false,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  return "mfa_required" in result ? result : storeSession(result);
}

export async function completeMfaLogin(
  challengeToken: string,
  code: string,
): Promise<LoginResponse> {
  const session = await jsonRequest<LoginResponse>(
    "/auth/mfa/challenge",
    "POST",
    { challenge_token: challengeToken, code },
    { auth: false, retry: false },
  );
  return storeSession(session);
}

export function requestPasswordReset(
  email: string,
): Promise<{ message: string }> {
  return jsonRequest<{ message: string }>(
    "/auth/password-reset",
    "POST",
    { email },
    { auth: false, retry: false },
  );
}

export function confirmPasswordReset(
  token: string,
  newPassword: string,
): Promise<{ message: string }> {
  return jsonRequest<{ message: string }>(
    "/auth/password-reset/confirm",
    "POST",
    { token, new_password: newPassword },
    { auth: false, retry: false },
  );
}

export async function registerFree(
  payload: FreeRegistrationPayload,
): Promise<LoginResponse> {
  const session = await jsonRequest<LoginResponse>(
    "/auth/register/free",
    "POST",
    payload,
    {
      auth: false,
      retry: false,
    },
  );
  return storeSession(session);
}

export async function logout(): Promise<void> {
  try {
    await jsonRequest<unknown>("/auth/logout", "POST", {});
  } finally {
    clearSession();
  }
}

export async function getCurrentUser(): Promise<User> {
  const user = await request<User>("/auth/me");
  if (user.role === "Super Owner") {
    clearSession();
    throw new Error("Session is not available on this portal");
  }
  writeStorage(STORAGE_KEYS.user, JSON.stringify(user));
  return user;
}

export function getPublicFreeTierPolicy(): Promise<FreeTierPublicPolicy> {
  return request<FreeTierPublicPolicy>("/auth/free-tier/public", {
    auth: false,
  });
}

export function getFirebasePhoneConfiguration(): Promise<FirebasePhoneConfiguration> {
  return request<FirebasePhoneConfiguration>("/auth/firebase/phone/public", {
    auth: false,
  });
}

export function getFirebasePhoneReadiness(
  phoneNumber: string,
  origin: string,
): Promise<FirebasePhoneReadiness> {
  const query = new URLSearchParams({ phone_number: phoneNumber, origin });
  return request<FirebasePhoneReadiness>(
    `/auth/firebase/phone/readiness?${query}`,
    {
      auth: false,
    },
  );
}

export function getFirebaseSocialConfiguration(): Promise<FirebaseSocialConfiguration> {
  return request<FirebaseSocialConfiguration>("/auth/firebase/social/public", {
    auth: false,
  });
}

export async function createFirebaseSocialSession(
  idToken: string,
): Promise<LoginResponse> {
  const session = await jsonRequest<LoginResponse>(
    "/auth/firebase/social/session",
    "POST",
    { id_token: idToken },
    { auth: false, retry: false },
  );
  return storeSession(session);
}

export function prepareFirebaseSocialRegistration(
  idToken: string,
): Promise<SocialRegistrationPreparation> {
  return jsonRequest<SocialRegistrationPreparation>(
    "/auth/firebase/social/registration/prepare",
    "POST",
    { id_token: idToken },
    { auth: false, retry: false },
  );
}

export function getPasskeyConfiguration(): Promise<PasskeyConfiguration> {
  return request<PasskeyConfiguration>("/auth/passkeys/public", {
    auth: false,
  });
}

export function listPasskeys(): Promise<PasskeyCredentialSummary[]> {
  return request<PasskeyCredentialSummary[]>("/auth/passkeys");
}

export function getPasskeyRegistrationOptions(): Promise<PasskeyCeremonyOptions> {
  return jsonRequest<PasskeyCeremonyOptions>(
    "/auth/passkeys/registration/options",
    "POST",
    {},
  );
}

export function verifyPasskeyRegistration(
  ceremonyId: string,
  credential: Record<string, unknown>,
  nickname: string,
): Promise<PasskeyCredentialSummary> {
  return jsonRequest<PasskeyCredentialSummary>(
    "/auth/passkeys/registration/verify",
    "POST",
    { ceremony_id: ceremonyId, credential, nickname },
  );
}

export function getPasskeyAuthenticationOptions(): Promise<PasskeyCeremonyOptions> {
  return jsonRequest<PasskeyCeremonyOptions>(
    "/auth/passkeys/authentication/options",
    "POST",
    {},
    { auth: false, retry: false },
  );
}

export async function verifyPasskeyAuthentication(
  ceremonyId: string,
  credential: Record<string, unknown>,
): Promise<LoginResponse> {
  const session = await jsonRequest<LoginResponse>(
    "/auth/passkeys/authentication/verify",
    "POST",
    { ceremony_id: ceremonyId, credential },
    { auth: false, retry: false },
  );
  return storeSession(session);
}

export function deletePasskey(passkeyId: string): Promise<void> {
  return request<void>(`/auth/passkeys/${encodeURIComponent(passkeyId)}`, {
    method: "DELETE",
  });
}

export function getMfaStatus(): Promise<MFAStatus> {
  return request<MFAStatus>("/auth/mfa/status");
}

export function startMfaSetup(): Promise<MFASetup> {
  return jsonRequest<MFASetup>("/auth/mfa/setup", "POST");
}

export function verifyMfaSetup(code: string): Promise<MFAStatus> {
  return jsonRequest<MFAStatus>("/auth/mfa/verify", "POST", { code });
}

export function disableMfa(
  currentPassword: string,
  code: string,
): Promise<MFAStatus> {
  return jsonRequest<MFAStatus>("/auth/mfa/disable", "POST", {
    current_password: currentPassword,
    code,
  });
}

export function listAccountSessions(): Promise<AccountSession[]> {
  return request<AccountSession[]>("/settings/sessions");
}

export function revokeAccountSession(
  sessionId: string,
): Promise<{ revoked: boolean }> {
  return request<{ revoked: boolean }>(
    `/settings/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}

export function getFreeTierStatus(): Promise<FreeTierStatus> {
  return request<FreeTierStatus>("/auth/free-tier");
}

export function getPublicBillingCatalog(): Promise<BillingCatalog> {
  return request<BillingCatalog>("/billing/catalog/public", { auth: false });
}

export function getBillingSummary(): Promise<BillingSummary> {
  return request<BillingSummary>("/billing");
}

export function listBillingPaymentMethods(): Promise<BillingPaymentMethod[]> {
  return request<BillingPaymentMethod[]>("/billing/payment-methods");
}

export function createBillingCheckout(
  payload: {
    plan_code: string;
    period_code: string;
    coupon_code?: string | null;
    billing_country?: string | null;
    locale?: string | null;
  },
  idempotencyKey: string,
): Promise<BillingCheckout> {
  return jsonRequest<BillingCheckout>("/billing/checkout", "POST", payload, {
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export function cancelBillingSubscription(
  immediately = false,
): Promise<BillingSubscriptionSummary> {
  return jsonRequest<BillingSubscriptionSummary>(
    "/billing/subscription/cancel",
    "POST",
    { immediately },
  );
}

export function createBillingPortalSession(
  locale?: string,
): Promise<{ url: string }> {
  return jsonRequest<{ url: string }>("/billing/portal-session", "POST", {
    locale: locale || null,
  });
}

export function changeBillingSubscription(
  payload: { plan_code: string; period_code: string },
  idempotencyKey: string,
): Promise<BillingSubscriptionSummary> {
  return jsonRequest<BillingSubscriptionSummary>(
    "/billing/subscription/change",
    "POST",
    payload,
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
}

export function resumeBillingSubscription(
  idempotencyKey: string,
): Promise<BillingSubscriptionSummary> {
  return jsonRequest<BillingSubscriptionSummary>(
    "/billing/subscription/resume",
    "POST",
    {},
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
}

export function setDefaultBillingPaymentMethod(
  methodId: string,
): Promise<BillingPaymentMethod> {
  return jsonRequest<BillingPaymentMethod>(
    `/billing/payment-methods/${encodeURIComponent(methodId)}/default`,
    "POST",
    {},
  );
}

export function removeBillingPaymentMethod(methodId: string): Promise<void> {
  return request<void>(
    `/billing/payment-methods/${encodeURIComponent(methodId)}`,
    { method: "DELETE" },
  );
}

export function validateBillingCoupon(
  code: string,
  amountMinor: number,
  currency: string,
): Promise<{ discount_minor: number; total_minor: number }> {
  return jsonRequest<{ discount_minor: number; total_minor: number }>(
    "/billing/coupons/validate",
    "POST",
    { code, amount_minor: amountMinor, currency },
  );
}

export function getSettings(): Promise<AccountSettings> {
  return request<AccountSettings>("/settings");
}

export function updateSettings(
  values: Partial<{
    name: string;
    avatar: string;
    language: string;
    timezone: string;
    theme: "dark" | "light" | "system";
    email_notifications: boolean;
    push_notifications: boolean;
  }>,
): Promise<AccountSettings> {
  return jsonRequest<AccountSettings>("/settings", "PATCH", values);
}

export function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ message: string }> {
  return jsonRequest<{ message: string }>("/settings/password", "POST", {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export function listWorkspaces(): Promise<Workspace[]> {
  return request<Workspace[]>("/workspaces");
}

export function listProjects(): Promise<Project[]> {
  return request<Project[]>("/projects");
}

export function createProject(payload: CreateProjectPayload): Promise<Project> {
  return jsonRequest<Project>("/projects", "POST", payload);
}

export function getProjectThreeDAccess(projectId: string): Promise<ThreeDAccess> {
  return request<ThreeDAccess>(`/projects/${encodeURIComponent(projectId)}/3d/access`);
}

export function listProjectThreeDJobs(projectId: string, limit = 20): Promise<ThreeDGenerationJob[]> {
  return request<ThreeDGenerationJob[]>(`/projects/${encodeURIComponent(projectId)}/3d/jobs?limit=${limit}`);
}

export function getProjectThreeDJob(projectId: string, jobId: string): Promise<ThreeDGenerationJob> {
  return request<ThreeDGenerationJob>(`/projects/${encodeURIComponent(projectId)}/3d/jobs/${encodeURIComponent(jobId)}`);
}

export function createProjectThreeDJob(
  projectId: string,
  image: File,
  values?: {
    seed?: number;
    textureSize?: number;
    termsAccepted?: boolean;
    termsVersion?: string;
  },
): Promise<ThreeDGenerationJob> {
  const body = new FormData();
  body.set("image", image);
  body.set("seed", String(values?.seed ?? 12345));
  if (values?.textureSize) body.set("texture_size", String(values.textureSize));
  body.set("third_party_terms_accepted", String(values?.termsAccepted === true));
  body.set("third_party_terms_version", values?.termsVersion || "");
  const idempotencyKey =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return request<ThreeDGenerationJob>(`/projects/${encodeURIComponent(projectId)}/3d/jobs`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body,
  });
}

export function cancelProjectThreeDJob(projectId: string, jobId: string): Promise<ThreeDGenerationJob> {
  return jsonRequest<ThreeDGenerationJob>(
    `/projects/${encodeURIComponent(projectId)}/3d/jobs/${encodeURIComponent(jobId)}/cancel`,
    "POST",
    {},
  );
}

export function clarifyProjectThreeDJob(
  projectId: string,
  jobId: string,
  image: File,
  values: { termsAccepted: boolean; termsVersion: string },
): Promise<ThreeDGenerationJob> {
  const body = new FormData();
  body.set("image", image);
  body.set("third_party_terms_accepted", String(values.termsAccepted));
  body.set("third_party_terms_version", values.termsVersion);
  return request<ThreeDGenerationJob>(
    `/projects/${encodeURIComponent(projectId)}/3d/jobs/${encodeURIComponent(jobId)}/clarify`,
    { method: "POST", body },
  );
}

export function getProjectThreeDArtifactLinks(projectId: string, jobId: string): Promise<ThreeDArtifactLinks> {
  return request<ThreeDArtifactLinks>(
    `/projects/${encodeURIComponent(projectId)}/3d/jobs/${encodeURIComponent(jobId)}/artifact`,
  );
}

export function getPhase36Capabilities(): Promise<Phase36ProgramSnapshot> {
  return request<Phase36ProgramSnapshot>("/capabilities/phase36", {
    auth: false,
    retry: false,
  });
}

export function listProjectExecutions(
  projectId: string,
  limit = 10,
): Promise<ProjectExecution[]> {
  return request<ProjectExecution[]>(
    `/projects/${encodeURIComponent(projectId)}/executions?limit=${limit}`,
  );
}

export function getProjectExecution(
  projectId: string,
  executionId: string,
): Promise<ProjectExecution> {
  return request<ProjectExecution>(
    `/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(executionId)}`,
  );
}

export function startProjectExecution(
  projectId: string,
  mode: "provider_neutral" | "full" | "3d_full" = "full",
  confirmExternalProcessing = mode === "full" || mode === "3d_full",
): Promise<ProjectExecution> {
  return jsonRequest<ProjectExecution>(
    `/projects/${encodeURIComponent(projectId)}/executions`,
    "POST",
    {
      confirm_external_processing: confirmExternalProcessing,
      mode,
    },
  );
}

export function approveProjectExecution(
  projectId: string,
  executionId: string,
  note?: string,
): Promise<ProjectExecution> {
  return jsonRequest<ProjectExecution>(
    `/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(executionId)}/approve`,
    "POST",
    {
      confirm_owner_approval: true,
      note: note?.trim() || null,
    },
  );
}

export function downloadProjectExecution(
  projectId: string,
  executionId: string,
): Promise<{ blob: Blob; filename: string }> {
  return downloadAuthenticated(
    `/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(executionId)}/download`,
  );
}

export function listNotifications(options?: {
  unreadOnly?: boolean;
  archived?: boolean;
  category?: string;
}): Promise<PortalNotification[]> {
  const query = new URLSearchParams();
  if (options?.unreadOnly) query.set("unread_only", "true");
  if (options?.archived) query.set("archived", "true");
  if (options?.category) query.set("category", options.category);
  const suffix = query.size ? `?${query.toString()}` : "";
  return request<{ items: PortalNotification[] }>(
    `/notifications${suffix}`,
  ).then((response) => response.items);
}

export function updateNotification(
  notificationId: string,
  values: { read?: boolean; archived?: boolean },
): Promise<PortalNotification> {
  return jsonRequest<PortalNotification>(
    `/notifications/${encodeURIComponent(notificationId)}`,
    "PATCH",
    values,
  );
}

export function markAllNotificationsRead(): Promise<{ updated: number }> {
  return jsonRequest<{ updated: number }>(
    "/notifications/mark-all-read",
    "POST",
    {},
  );
}

export function acknowledgeNotificationDelivery(
  deliveryId: string,
): Promise<PortalNotification["deliveries"][number]> {
  return jsonRequest<PortalNotification["deliveries"][number]>(
    `/notifications/deliveries/${encodeURIComponent(deliveryId)}/acknowledge`,
    "POST",
    {},
  );
}

export function getCommunicationChannels(): Promise<
  CommunicationChannelReadiness[]
> {
  return request<CommunicationChannelReadiness[]>("/communications/channels");
}

export function listCommunicationEndpoints(): Promise<CommunicationEndpoint[]> {
  return request<CommunicationEndpoint[]>("/communications/endpoints");
}

export function registerCommunicationEndpoint(values: {
  channel: CommunicationEndpoint["channel"];
  address: string;
  label: string;
}): Promise<CommunicationEndpoint> {
  return jsonRequest<CommunicationEndpoint>(
    "/communications/endpoints",
    "POST",
    values,
  );
}

export function deleteCommunicationEndpoint(endpointId: string): Promise<void> {
  return request<void>(
    `/communications/endpoints/${encodeURIComponent(endpointId)}`,
    { method: "DELETE" },
  );
}

export function getNotificationPreferences(): Promise<
  NotificationPreference[]
> {
  return request<NotificationPreference[]>("/communications/preferences");
}

export function updateNotificationPreference(values: {
  category: string;
  enabled: boolean;
  channels: NotificationPreference["channels"];
  minimum_severity: NotificationPreference["minimum_severity"];
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
  timezone: string;
  digest_mode: NotificationPreference["digest_mode"];
}): Promise<NotificationPreference> {
  return jsonRequest<NotificationPreference>(
    "/communications/preferences",
    "PUT",
    values,
  );
}

export function createSupportRequest(
  subject: string,
  message: string,
  options?: { category?: string; priority?: string },
): Promise<SupportTicket> {
  return jsonRequest<SupportTicket>("/support/requests", "POST", {
    subject,
    message,
    category: options?.category || "general",
    priority: options?.priority || "normal",
  });
}

export function listSupportRequests(): Promise<SupportTicket[]> {
  return request<SupportTicket[]>("/support/requests");
}

export function getSupportRequest(requestId: string): Promise<SupportTicket> {
  return request<SupportTicket>(
    `/support/requests/${encodeURIComponent(requestId)}`,
  );
}

export function replyToSupportRequest(
  requestId: string,
  message: string,
): Promise<SupportTicketMessage> {
  return jsonRequest<SupportTicketMessage>(
    `/support/requests/${encodeURIComponent(requestId)}/messages`,
    "POST",
    { message, visibility: "requester" },
  );
}

export function getSecurityLabAccess(): Promise<SecurityLabAccess> {
  return request<SecurityLabAccess>("/security-lab/access");
}

export function listSecurityTools(): Promise<SecurityTool[]> {
  return request<SecurityTool[]>("/security-lab/tools");
}

export function listSecurityTargets(): Promise<SecurityTargetRecord[]> {
  return request<SecurityTargetRecord[]>("/security-lab/targets");
}

export function registerExternalSecurityTarget(
  origin: string,
): Promise<
  SecurityTargetRecord & {
    verification: SecurityVerificationInstructions;
  }
> {
  return jsonRequest(
    "/security-lab/targets/external",
    "POST",
    { origin },
  );
}

export function verifyExternalSecurityTarget(
  targetId: string,
  challenge: string,
  method: SecurityVerificationMethod = "http_file",
): Promise<SecurityTargetRecord> {
  return jsonRequest<SecurityTargetRecord>(
    `/security-lab/targets/${encodeURIComponent(targetId)}/verify`,
    "POST",
    { challenge, method },
  );
}

export function removeSecurityTarget(
  targetId: string,
): Promise<SecurityTargetRecord> {
  return jsonRequest<SecurityTargetRecord>(
    `/security-lab/targets/${encodeURIComponent(targetId)}`,
    "DELETE",
  );
}

export function getSecurityScanReport(
  scanId: string,
): Promise<SecurityScanReport> {
  return request<SecurityScanReport>(
    `/security-lab/scans/${encodeURIComponent(scanId)}/report`,
  );
}

export function listSecurityScans(): Promise<SecurityScanRecord[]> {
  return request<SecurityScanRecord[]>("/security-lab/scans");
}

export function createSecurityScan(
  targetId: string,
  profile: SecurityProfile,
): Promise<SecurityScanRecord> {
  return jsonRequest<SecurityScanRecord>("/security-lab/scans", "POST", {
    target_id: targetId,
    profile,
  });
}

export function cancelSecurityScan(scanId: string): Promise<SecurityScanRecord> {
  return jsonRequest<SecurityScanRecord>(
    `/security-lab/scans/${encodeURIComponent(scanId)}/cancel`,
    "POST",
    {},
  );
}

export function listSecurityFindings(
  scanId: string,
): Promise<SecurityFindingRecord[]> {
  return request<SecurityFindingRecord[]>(
    `/security-lab/scans/${encodeURIComponent(scanId)}/findings`,
  );
}

export function listSecurityRemediations(): Promise<SecurityRemediationRecord[]> {
  return request<SecurityRemediationRecord[]>("/security-lab/remediations");
}

export function requestSecurityRemediation(
  findingId: string,
): Promise<SecurityRemediationRecord> {
  return jsonRequest<SecurityRemediationRecord>(
    "/security-lab/remediations",
    "POST",
    { finding_id: findingId },
  );
}

export function queueSecurityRemediationRetest(
  remediationId: string,
): Promise<{ remediation: SecurityRemediationRecord; scan: SecurityScanRecord }> {
  return jsonRequest(
    `/security-lab/remediations/${encodeURIComponent(remediationId)}/retest`,
    "POST",
    {},
  );
}

export function finalizeSecurityRemediation(
  remediationId: string,
): Promise<SecurityRemediationRecord> {
  return jsonRequest<SecurityRemediationRecord>(
    `/security-lab/remediations/${encodeURIComponent(remediationId)}/finalize`,
    "POST",
    {},
  );
}

export function collectRegistrationTelemetry(): RegistrationTelemetry {
  if (typeof window === "undefined" || typeof navigator === "undefined")
    return {};
  const extendedNavigator = navigator as Navigator & {
    deviceMemory?: number;
    connection?: {
      type?: string;
      effectiveType?: string;
      downlink?: number;
      rtt?: number;
      saveData?: boolean;
    };
    webdriver?: boolean;
  };
  const connection = extendedNavigator.connection;
  return {
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    language: navigator.language,
    platform: navigator.platform,
    user_agent: navigator.userAgent,
    screen: `${window.screen.width}x${window.screen.height}`,
    screen_width: window.screen.width,
    screen_height: window.screen.height,
    color_depth: window.screen.colorDepth,
    device_memory_gb: extendedNavigator.deviceMemory,
    hardware_concurrency: navigator.hardwareConcurrency,
    max_touch_points: navigator.maxTouchPoints,
    cookie_enabled: navigator.cookieEnabled,
    do_not_track: navigator.doNotTrack === "1",
    connection_type: connection?.type,
    effective_type: connection?.effectiveType,
    downlink_mbps: connection?.downlink,
    rtt_ms: connection?.rtt,
    save_data: connection?.saveData,
    referrer: document.referrer || undefined,
    vendor: navigator.vendor,
    webdriver: extendedNavigator.webdriver,
  };
}

export function getUserTelegramStatus(): Promise<UserTelegramStatus> {
  return request<UserTelegramStatus>("/telegram/status");
}

export function createUserTelegramLinkChallenge(): Promise<UserTelegramChallenge> {
  return jsonRequest<UserTelegramChallenge>("/telegram/link-challenge", "POST", {});
}

export function revokeUserTelegramLink(): Promise<{ revoked: boolean }> {
  return request<{ revoked: boolean }>("/telegram/link", { method: "DELETE" });
}

export function getPaidCampaignReadiness(): Promise<PaidCampaignReadiness> {
  return request<PaidCampaignReadiness>(
    "/growth-social/paid-campaigns/readiness",
  );
}

export function listPaidCampaigns(): Promise<PaidCampaign[]> {
  return request<{ items: PaidCampaign[] }>("/growth-social/paid-campaigns").then(
    (response) => response.items,
  );
}

export function prepareAndSimulatePaidCampaign(
  input: PaidCampaignPreparationInput,
): Promise<PaidCampaignPreparationResult> {
  return jsonRequest<PaidCampaignPreparationResult>(
    "/growth-social/paid-campaigns/prepare-and-simulate",
    "POST",
    input,
  );
}

// --- Social connectors (P3). Tokens never reach the browser; only account
// metadata, scopes and health come back from these routes.

export function listSocialProviders(): Promise<{ items: SocialProvider[] }> {
  return request<{ items: SocialProvider[] }>("/social/providers");
}

export function startSocialConnect(
  provider: string,
  locale: string,
): Promise<{ authorize_url: string; expires_in: number }> {
  return jsonRequest(
    `/social/connect/${encodeURIComponent(provider)}/start`,
    "POST",
    { locale },
  );
}

export function listSocialConnections(): Promise<{ items: SocialConnection[] }> {
  return request<{ items: SocialConnection[] }>("/social/connections");
}

export function listSocialConnectionAssets(
  connectionId: string,
): Promise<{ connection: SocialConnection; items: SocialAsset[] }> {
  return request(`/social/connections/${encodeURIComponent(connectionId)}/assets`);
}

export function connectSocialAssets(
  connectionId: string,
  assetIds: string[],
): Promise<SocialConnectResult> {
  return jsonRequest<SocialConnectResult>(
    `/social/connections/${encodeURIComponent(connectionId)}/assets`,
    "POST",
    { asset_ids: assetIds },
  );
}

export function disconnectSocialConnection(
  connectionId: string,
): Promise<{ connection: SocialConnection; provider_revoked: boolean }> {
  return jsonRequest(
    `/social/connections/${encodeURIComponent(connectionId)}`,
    "DELETE",
  );
}

export function listSocialAccounts(): Promise<{ items: SocialAccount[] }> {
  return request<{ items: SocialAccount[] }>("/social/accounts");
}

export function checkSocialAccountHealth(accountId: string): Promise<SocialAccount> {
  return jsonRequest<SocialAccount>(
    `/social/accounts/${encodeURIComponent(accountId)}/health`,
    "POST",
  );
}

export function disconnectSocialAccount(accountId: string): Promise<SocialDisconnectResult> {
  return jsonRequest<SocialDisconnectResult>(
    `/social/accounts/${encodeURIComponent(accountId)}`,
    "DELETE",
  );
}

// --- Social publishing (P3 3.3-3.5). The worker publishes; these routes only
// queue, schedule, cancel and read Graph results recorded by the server.

export function listSocialPosts(range?: {
  start: string;
  end: string;
}): Promise<{ items: SocialPost[] }> {
  const query = range
    ? `?${new URLSearchParams({ start: range.start, end: range.end }).toString()}`
    : "";
  return request<{ items: SocialPost[] }>(`/social/posts${query}`);
}

export function getSocialPost(postId: string): Promise<SocialPost> {
  return request<SocialPost>(`/social/posts/${encodeURIComponent(postId)}`);
}

export function validateSocialPost(input: SocialPostInput): Promise<SocialValidationReport> {
  return jsonRequest<SocialValidationReport>("/social/posts/validate", "POST", input);
}

export function createSocialPost(input: SocialPostInput): Promise<SocialPost> {
  return jsonRequest<SocialPost>("/social/posts", "POST", input);
}

export function updateSocialPost(postId: string, input: SocialPostInput): Promise<SocialPost> {
  return jsonRequest<SocialPost>(`/social/posts/${encodeURIComponent(postId)}`, "PATCH", input);
}

export function deleteSocialPost(postId: string): Promise<{ id: string; deleted: boolean }> {
  return jsonRequest(`/social/posts/${encodeURIComponent(postId)}`, "DELETE");
}

export function scheduleSocialPost(
  postId: string,
  scheduledAt: string,
  timezone: string,
): Promise<SocialPost> {
  return jsonRequest<SocialPost>(
    `/social/posts/${encodeURIComponent(postId)}/schedule`,
    "POST",
    { scheduled_at: scheduledAt, timezone },
  );
}

export function publishSocialPostNow(postId: string): Promise<SocialPost> {
  return jsonRequest<SocialPost>(`/social/posts/${encodeURIComponent(postId)}/publish`, "POST", {});
}

export function cancelSocialPost(postId: string): Promise<SocialPost> {
  return jsonRequest<SocialPost>(`/social/posts/${encodeURIComponent(postId)}/cancel`, "POST", {});
}

export function listSocialMedia(): Promise<{
  uploads: SocialMediaItem[];
  studio: SocialMediaItem[];
}> {
  return request("/social/media");
}

export function uploadSocialMedia(file: File): Promise<SocialMediaItem> {
  const body = new FormData();
  body.set("file", file);
  return request<SocialMediaItem>("/social/media", { method: "POST", body });
}

export function deleteSocialMedia(mediaId: string): Promise<{ id: string; deleted: boolean }> {
  return jsonRequest(`/social/media/${encodeURIComponent(mediaId)}`, "DELETE");
}

export function socialAiAssist(input: {
  mode: "draft" | "improve" | "hashtags";
  text: string;
  topic: string;
  language: string;
  platforms: ("facebook" | "instagram")[];
  tone: string;
}): Promise<SocialAiAssistResult> {
  return jsonRequest<SocialAiAssistResult>("/social/ai/assist", "POST", input);
}

// --- Meta Ads for users (P4). The ads permission is requested incrementally on
// the Meta login; campaigns are created PAUSED and activation needs a typed
// confirmation under the Owner spend caps. No token ever reaches the browser.

export function getAdsAccess(): Promise<AdsAccess> {
  return request<AdsAccess>("/ads/access");
}

export function startAdsConnect(locale: string): Promise<{ authorize_url: string; expires_in: number }> {
  return jsonRequest("/ads/connect/meta/start", "POST", { locale });
}

export function listAdsConnections(): Promise<{ items: AdsConnection[] }> {
  return request<{ items: AdsConnection[] }>("/ads/connections");
}

export function listAvailableAdAccounts(input: {
  source: "oauth" | "owner_token";
  connectionId?: string | null;
}): Promise<{ items: AdsAvailableAccount[] }> {
  const query = new URLSearchParams({ source: input.source });
  if (input.connectionId) query.set("connection_id", input.connectionId);
  return request<{ items: AdsAvailableAccount[] }>(`/ads/accounts/available?${query.toString()}`);
}

export function linkAdAccounts(input: {
  source: "oauth" | "owner_token";
  connection_id?: string | null;
  ad_account_ids: string[];
}): Promise<{ items: AdAccountLink[] }> {
  return jsonRequest("/ads/accounts", "POST", input);
}

export function listAdAccountLinks(): Promise<{ items: AdAccountLink[] }> {
  return request<{ items: AdAccountLink[] }>("/ads/accounts");
}

export function updateAdAccountLink(linkId: string, input: { cpa_target_minor: number | null }): Promise<AdAccountLink> {
  return jsonRequest<AdAccountLink>(`/ads/accounts/${encodeURIComponent(linkId)}`, "PATCH", input);
}

export function unlinkAdAccount(linkId: string): Promise<AdAccountLink> {
  return jsonRequest<AdAccountLink>(`/ads/accounts/${encodeURIComponent(linkId)}`, "DELETE");
}

export function requestAdAccountSync(linkId: string): Promise<AdAccountLink> {
  return jsonRequest<AdAccountLink>(`/ads/accounts/${encodeURIComponent(linkId)}/sync`, "POST", {});
}

export function getAdsAnalytics(linkId: string, range?: { from: string; to: string }): Promise<AdsDashboard> {
  const query = new URLSearchParams({ link_id: linkId });
  if (range) {
    query.set("date_from", range.from);
    query.set("date_to", range.to);
  }
  return request<AdsDashboard>(`/ads/analytics?${query.toString()}`);
}

export function getAdsUsage(linkId: string): Promise<AdsUsage> {
  return request<AdsUsage>(`/ads/usage?${new URLSearchParams({ link_id: linkId }).toString()}`);
}

export function createAdsRecommendations(input: {
  link_id: string;
  language: string;
  external_processing_confirmed: boolean;
}): Promise<AdsRecommendationRun> {
  return jsonRequest<AdsRecommendationRun>("/ads/recommendations", "POST", input);
}

export function getLatestAdsRecommendations(linkId: string): Promise<{ item: AdsRecommendationRun | null }> {
  return request(`/ads/recommendations?${new URLSearchParams({ link_id: linkId }).toString()}`);
}

export function listAdsCampaigns(): Promise<{ items: AdsCampaign[] }> {
  return request<{ items: AdsCampaign[] }>("/ads/campaigns");
}

export function createAdsCampaign(input: AdsCampaignInput): Promise<AdsCampaign> {
  return jsonRequest<AdsCampaign>("/ads/campaigns", "POST", input);
}

export function provisionAdsCampaign(campaignId: string): Promise<AdsCampaign> {
  return jsonRequest<AdsCampaign>(`/ads/campaigns/${encodeURIComponent(campaignId)}/provision`, "POST", {});
}

export function activateAdsCampaign(
  campaignId: string,
  input: { confirmation: string; confirmed_budget_minor: number },
): Promise<AdsCampaign> {
  return jsonRequest<AdsCampaign>(`/ads/campaigns/${encodeURIComponent(campaignId)}/activate`, "POST", input);
}

export function pauseAdsCampaign(campaignId: string): Promise<AdsCampaign> {
  return jsonRequest<AdsCampaign>(`/ads/campaigns/${encodeURIComponent(campaignId)}/pause`, "POST", {});
}

// --- Social unified inbox (P3 3.6). Replies go through the Graph API on the
// server; DMs outside Meta's 24-hour window are refused there.

export function getSocialInboxStatus(): Promise<SocialInboxReadiness> {
  return request<SocialInboxReadiness>("/social/inbox/status");
}

export function subscribeSocialInboxAccount(accountId: string): Promise<SocialInboxAccountReadiness> {
  return jsonRequest<SocialInboxAccountReadiness>(
    `/social/inbox/accounts/${encodeURIComponent(accountId)}/subscribe`,
    "POST",
    {},
  );
}

export function listSocialInboxConversations(filters: {
  platform?: "facebook" | "instagram";
  channel?: "comment" | "dm";
  unread?: boolean;
  status?: "open" | "pending" | "closed";
} = {}): Promise<{ items: SocialInboxConversation[]; unread_conversations: number; has_more: boolean }> {
  const params = new URLSearchParams();
  if (filters.platform) params.set("platform", filters.platform);
  if (filters.channel) params.set("channel", filters.channel);
  if (filters.unread !== undefined) params.set("unread", String(filters.unread));
  if (filters.status) params.set("status", filters.status);
  const query = params.toString() ? `?${params.toString()}` : "";
  return request(`/social/inbox/conversations${query}`);
}

export function getSocialInboxConversation(conversationId: string): Promise<SocialInboxThread> {
  return request<SocialInboxThread>(`/social/inbox/conversations/${encodeURIComponent(conversationId)}`);
}

export function updateSocialInboxConversation(
  conversationId: string,
  changes: { read?: boolean; status?: "open" | "pending" | "closed"; assigned_to_id?: string; unassign?: boolean },
): Promise<SocialInboxThread> {
  return jsonRequest<SocialInboxThread>(
    `/social/inbox/conversations/${encodeURIComponent(conversationId)}`,
    "PATCH",
    changes,
  );
}

export function replySocialInboxConversation(conversationId: string, text: string): Promise<SocialInboxThread> {
  return jsonRequest<SocialInboxThread>(
    `/social/inbox/conversations/${encodeURIComponent(conversationId)}/reply`,
    "POST",
    { text },
  );
}

export function suggestSocialInboxReply(
  conversationId: string,
  input: { language: string; tone: string },
): Promise<SocialInboxSuggestion> {
  return jsonRequest<SocialInboxSuggestion>(
    `/social/inbox/conversations/${encodeURIComponent(conversationId)}/suggest`,
    "POST",
    input,
  );
}

export function setSocialInboxMessageVisibility(messageId: string, hidden: boolean): Promise<SocialInboxThread> {
  return jsonRequest<SocialInboxThread>(
    `/social/inbox/messages/${encodeURIComponent(messageId)}/visibility`,
    "POST",
    { hidden },
  );
}

// Public status of a Meta data-deletion request (no sign-in needed).
export function getMetaDataDeletionStatus(code: string): Promise<MetaDataDeletionStatus> {
  return request<MetaDataDeletionStatus>(
    `/social/meta/data-deletion/status?code=${encodeURIComponent(code)}`,
    { auth: false },
  );
}
