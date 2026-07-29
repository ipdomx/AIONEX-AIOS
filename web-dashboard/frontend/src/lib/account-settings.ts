import { apiClient } from "@/lib/api-client";

export type AccountSettings = {
  profile: {
    id: string;
    name: string;
    email: string;
    role: string;
    organization: string;
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
  };
};

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
