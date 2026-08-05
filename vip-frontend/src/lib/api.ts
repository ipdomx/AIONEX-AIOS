import type {
  AccountSettings,
  CreateProjectPayload,
  FirebasePhoneConfiguration,
  FirebasePhoneReadiness,
  FirebaseSocialConfiguration,
  FreeRegistrationPayload,
  FreeTierPublicPolicy,
  FreeTierStatus,
  LoginResponse,
  PasskeyCeremonyOptions,
  PasskeyConfiguration,
  PasskeyCredentialSummary,
  Project,
  ProjectExecution,
  RegistrationTelemetry,
  SocialRegistrationPreparation,
  User,
  Workspace,
} from "@/types";

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
  writeStorage(STORAGE_KEYS.access, session.access_token);
  writeStorage(STORAGE_KEYS.refresh, session.refresh_token);
  writeStorage(STORAGE_KEYS.user, JSON.stringify(session.user));
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
  return Boolean(
    readStorage(STORAGE_KEYS.access) && readStorage(STORAGE_KEYS.refresh),
  );
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

let refreshInFlight: Promise<LoginResponse> | null = null;

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

async function refreshSession(): Promise<LoginResponse> {
  if (refreshInFlight) return refreshInFlight;
  const refreshToken = readStorage(STORAGE_KEYS.refresh);
  if (!refreshToken) throw new ApiError(401, "No refresh session", null, null);

  refreshInFlight = (async () => {
    const response = await fetch(`${API_ROOT}/auth/refresh`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    const payload = await responsePayload(response);
    if (!response.ok) {
      clearSession();
      throw apiError(response, payload);
    }
    return storeSession(payload as LoginResponse);
  })().finally(() => {
    refreshInFlight = null;
  });

  return refreshInFlight;
}

async function request<T>(
  path: string,
  { auth = true, retry = true, ...init }: ApiRequestOptions = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const accessToken = readStorage(STORAGE_KEYS.access);
  if (auth && accessToken)
    headers.set("Authorization", `Bearer ${accessToken}`);

  const response = await fetch(`${API_ROOT}${path}`, {
    credentials: "include",
    ...init,
    headers,
  });
  if (
    response.status === 401 &&
    auth &&
    retry &&
    readStorage(STORAGE_KEYS.refresh)
  ) {
    await refreshSession();
    return request<T>(path, { ...init, auth, retry: false });
  }

  const payload = await responsePayload(response);
  if (!response.ok) throw apiError(response, payload);
  return payload as T;
}

async function downloadRequest(
  path: string,
  retry = true,
): Promise<{ blob: Blob; filename: string }> {
  const headers = new Headers({ Accept: "application/zip" });
  const accessToken = readStorage(STORAGE_KEYS.access);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(`${API_ROOT}${path}`, {
    credentials: "include",
    headers,
  });
  if (response.status === 401 && retry && readStorage(STORAGE_KEYS.refresh)) {
    await refreshSession();
    return downloadRequest(path, false);
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

function jsonRequest<T>(
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
): Promise<LoginResponse> {
  const body = new URLSearchParams({ username: email.trim(), password });
  const session = await request<LoginResponse>("/auth/login", {
    method: "POST",
    auth: false,
    retry: false,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  return storeSession(session);
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
  const refreshToken = readStorage(STORAGE_KEYS.refresh);
  try {
    await jsonRequest<unknown>("/auth/logout", "POST", {
      refresh_token: refreshToken,
    });
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

export function getFreeTierStatus(): Promise<FreeTierStatus> {
  return request<FreeTierStatus>("/auth/free-tier");
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
): Promise<ProjectExecution> {
  return jsonRequest<ProjectExecution>(
    `/projects/${encodeURIComponent(projectId)}/executions`,
    "POST",
    { confirm_external_processing: true, mode: "full" },
  );
}

export function downloadProjectExecution(
  projectId: string,
  executionId: string,
): Promise<{ blob: Blob; filename: string }> {
  return downloadRequest(
    `/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(executionId)}/download`,
  );
}

export function createSupportRequest(
  subject: string,
  message: string,
): Promise<{ status: "accepted"; request_id: string }> {
  return jsonRequest<{ status: "accepted"; request_id: string }>(
    "/support/requests",
    "POST",
    { subject, message },
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
