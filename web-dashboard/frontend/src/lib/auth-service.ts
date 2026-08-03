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
