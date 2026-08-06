import { apiClient } from "@/lib/api-client";
import type { FreeTierStatus } from "@/lib/auth-service";

export type AccountSettings = {
  profile: {
    id: string;
    name: string;
    email: string;
    role: string;
    organization: string;
    avatar?: string | null;
  };
  preferences: {
    language: string;
    timezone: string;
    theme: "dark" | "light" | "system";
    email_notifications: boolean;
    push_notifications: boolean;
  };
  security: {
    mfa_policy_enabled: boolean;
    active_sessions: number;
    password_min_length: number;
    mfa_enabled: boolean;
    mfa_backup_codes_remaining: number;
    passkey_count: number;
  };
  free_tier?: FreeTierStatus | null;
};

export type MFAStatus = {
  enabled: boolean;
  backup_codes_remaining: number;
  verified_at: string | null;
};

export type MFASetup = {
  secret: string;
  qr_code: string;
  backup_codes: string[];
};

export type AccountSession = {
  id: string;
  created_at: string;
  updated_at: string;
  expires_at: string;
  revoked_at: string | null;
  active: boolean;
  ip_address: string | null;
  user_agent: string | null;
};

export function fetchMFAStatus(): Promise<MFAStatus> {
  return apiClient.get<MFAStatus>("/auth/mfa/status");
}

export function startMFASetup(): Promise<MFASetup> {
  return apiClient.post<MFASetup>("/auth/mfa/setup", {});
}

export function verifyMFASetup(code: string): Promise<MFAStatus> {
  return apiClient.post<MFAStatus>("/auth/mfa/verify", { code });
}

export function disableMFA(
  currentPassword: string,
  code: string,
): Promise<MFAStatus> {
  return apiClient.post<MFAStatus>("/auth/mfa/disable", {
    current_password: currentPassword,
    code,
  });
}

export function fetchAccountSessions(): Promise<AccountSession[]> {
  return apiClient.get<AccountSession[]>("/settings/sessions");
}

export function revokeAccountSession(
  sessionId: string,
): Promise<{ revoked: boolean }> {
  return apiClient.delete<{ revoked: boolean }>(
    `/settings/sessions/${encodeURIComponent(sessionId)}`,
  );
}

export function fetchAccountSettings(
  signal?: AbortSignal,
): Promise<AccountSettings> {
  return apiClient.get<AccountSettings>("/settings", { signal });
}

export function updateAccountSettings(
  payload: Record<string, unknown>,
): Promise<AccountSettings> {
  return apiClient.patch<AccountSettings>("/settings", payload);
}

export function changeAccountPassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ message: string }> {
  return apiClient.post<{ message: string }>("/settings/password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export function revokeAccountSessions(): Promise<{ revoked: number }> {
  return apiClient.delete<{ revoked: number }>("/settings/sessions");
}
