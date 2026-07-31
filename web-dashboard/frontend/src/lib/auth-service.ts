import { apiClient } from "@/lib/api-client";

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: string;
  status: string;
  avatar?: string | null;
  organization: {
    id: string;
    name: string;
    plan: string;
  };
  permissions: string[];
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

export type FreeTierPublicPolicy = {
  enabled: boolean;
  plan: "free";
  limits: {
    projects: number;
    user_messages_per_month: number;
    assistant_responses_per_month: number;
    storage_bytes: number;
    max_message_characters: number;
  };
  consent_version: string;
  identity: {
    minimum_age: number;
    phone_verification_required: boolean;
    device_signals_required: boolean;
    one_account_per_network: boolean;
    one_account_per_device: boolean;
  };
  required_registration_data: string[];
};

export type FreeTierStatus = {
  plan: string;
  free_tier: boolean;
  enabled?: boolean;
  limits?: {
    projects: number;
    user_messages: number;
    assistant_responses: number;
    storage_bytes: number;
    max_message_characters: number;
  };
  usage?: {
    projects: number;
    user_messages: number;
    assistant_responses: number;
    storage_bytes: number;
  };
  remaining?: {
    projects: number;
    user_messages: number;
    assistant_responses: number;
    storage_bytes: number;
  };
  period_started_at?: string;
  period_ends_at?: string;
};

export type FreeRegistrationTelemetry = {
  timezone?: string;
  language?: string;
  platform?: string;
  user_agent?: string;
  screen?: string;
  screen_width?: number;
  screen_height?: number;
  color_depth?: number;
  device_memory_gb?: number;
  hardware_concurrency?: number;
  max_touch_points?: number;
  cookie_enabled?: boolean;
  do_not_track?: boolean;
  connection_type?: string;
  effective_type?: string;
  downlink_mbps?: number;
  rtt_ms?: number;
  save_data?: boolean;
  referrer?: string;
  vendor?: string;
  webdriver?: boolean;
};

export type FreeRegistrationPayload = {
  username: string;
  name: string;
  email: string;
  password: string;
  birth_date: string;
  country_code: string;
  phone_number: string;
  phone_verification_token: string;
  consent_accepted: boolean;
  consent_version: string;
  telemetry: FreeRegistrationTelemetry;
};

const ACCESS_TOKEN_KEY = "aionex.access_token";
const REFRESH_TOKEN_KEY = "aionex.refresh_token";
const USER_KEY = "aionex.user";
const CONSENT_COOKIE = "aionex_cookie_consent";

function saveSession(response: LoginResponse): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ACCESS_TOKEN_KEY, response.access_token);
  window.localStorage.setItem(REFRESH_TOKEN_KEY, response.refresh_token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(response.user));
}

function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

function saveEssentialConsent(version: string): void {
  if (typeof document === "undefined") return;
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  const value = encodeURIComponent(
    JSON.stringify({ categories: ["essential", "security", "quota", "device"], version }),
  );
  document.cookie = `${CONSENT_COOKIE}=${value}; Max-Age=31536000; Path=/; SameSite=Lax${secure}`;
}

type NetworkInformation = {
  type?: string;
  effectiveType?: string;
  downlink?: number;
  rtt?: number;
  saveData?: boolean;
};

type TelemetryNavigator = Navigator & {
  deviceMemory?: number;
  connection?: NetworkInformation;
  mozConnection?: NetworkInformation;
  webkitConnection?: NetworkInformation;
};

export function collectRegistrationTelemetry(): FreeRegistrationTelemetry {
  if (typeof window === "undefined" || typeof navigator === "undefined") return {};
  const telemetryNavigator = navigator as TelemetryNavigator;
  const connection =
    telemetryNavigator.connection ??
    telemetryNavigator.mozConnection ??
    telemetryNavigator.webkitConnection;
  return {
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    language: navigator.language,
    platform: navigator.platform,
    user_agent: navigator.userAgent,
    screen: `${window.screen.width}x${window.screen.height}`,
    screen_width: window.screen.width,
    screen_height: window.screen.height,
    color_depth: window.screen.colorDepth,
    device_memory_gb: telemetryNavigator.deviceMemory,
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
    vendor: navigator.vendor || undefined,
    webdriver: navigator.webdriver,
  };
}

export const authService = {
  async login(email: string, password: string): Promise<LoginResponse> {
    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);
    const response = await apiClient.post<LoginResponse>("/auth/login", body, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    saveSession(response);
    return response;
  },

  async registerFree(payload: FreeRegistrationPayload): Promise<LoginResponse> {
    const response = await apiClient.post<LoginResponse>("/auth/register/free", payload);
    saveEssentialConsent(payload.consent_version);
    saveSession(response);
    return response;
  },

  async getPublicFreeTierPolicy(): Promise<FreeTierPublicPolicy> {
    return apiClient.get<FreeTierPublicPolicy>("/auth/free-tier/public");
  },

  async getFreeTierStatus(): Promise<FreeTierStatus> {
    return apiClient.get<FreeTierStatus>("/auth/free-tier");
  },

  async logout(): Promise<void> {
    try {
      const refreshToken =
        typeof window === "undefined"
          ? null
          : window.localStorage.getItem(REFRESH_TOKEN_KEY);
      await apiClient.post<{ message: string }>("/auth/logout", {
        refresh_token: refreshToken,
      });
    } finally {
      clearSession();
    }
  },

  async currentUser(): Promise<AuthUser> {
    return apiClient.get<AuthUser>("/auth/me");
  },

  async refresh(): Promise<LoginResponse> {
    if (typeof window === "undefined") {
      throw new Error("Refresh requires a browser session");
    }
    const refreshToken = window.localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refreshToken) throw new Error("No refresh token available");
    const response = await apiClient.post<LoginResponse>("/auth/refresh", {
      refresh_token: refreshToken,
    });
    saveSession(response);
    return response;
  },

  getStoredUser(): AuthUser | null {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as AuthUser;
    } catch {
      clearSession();
      return null;
    }
  },

  hasAccessToken(): boolean {
    return (
      typeof window !== "undefined" &&
      Boolean(window.localStorage.getItem(ACCESS_TOKEN_KEY))
    );
  },

  clearSession,
};
