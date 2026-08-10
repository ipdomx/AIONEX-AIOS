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

export interface MFAChallengeResponse {
  mfa_required: true;
  challenge_token: string;
  expires_in: number;
}

export type LoginAttempt = LoginResponse | MFAChallengeResponse;

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

const ACCESS_TOKEN_KEY = "aionex.access_token";
const REFRESH_TOKEN_KEY = "aionex.refresh_token";
const USER_KEY = "aionex.user";

function saveSession(response: LoginResponse): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  window.localStorage.setItem(USER_KEY, JSON.stringify(response.user));
}

function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export const authService = {
  async login(email: string, password: string): Promise<LoginAttempt> {
    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);
    const response = await apiClient.post<LoginAttempt>("/auth/login", body, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    if (!("mfa_required" in response)) saveSession(response);
    return response;
  },

  async completeMfa(
    challengeToken: string,
    code: string,
  ): Promise<LoginResponse> {
    const response = await apiClient.post<LoginResponse>(
      "/auth/mfa/challenge",
      {
        challenge_token: challengeToken,
        code,
      },
    );
    saveSession(response);
    return response;
  },

  async getFreeTierStatus(): Promise<FreeTierStatus> {
    return apiClient.get<FreeTierStatus>("/auth/free-tier");
  },

  async logout(): Promise<void> {
    try {
      await apiClient.post<{ message: string }>("/auth/logout", {});
    } finally {
      clearSession();
    }
  },

  async currentUser(): Promise<AuthUser> {
    return apiClient.get<AuthUser>("/auth/me");
  },

  async refresh(): Promise<LoginResponse> {
    const response = await apiClient.post<LoginResponse>("/auth/refresh", {});
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
    return typeof window !== "undefined" && Boolean(window.localStorage.getItem(USER_KEY));
  },

  clearSession,
};
