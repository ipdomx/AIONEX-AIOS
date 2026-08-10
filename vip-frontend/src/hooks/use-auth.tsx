"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  clearSession,
  completeMfaLogin,
  createFirebaseSocialSession,
  getCurrentUser,
  login as apiLogin,
  logout as apiLogout,
  registerFree as apiRegisterFree,
  storedUser,
} from "@/lib/api";
import { firebaseSocialIdToken } from "@/lib/firebase-social-auth";
import { authenticateWithPasskey } from "@/lib/passkeys";
import type {
  FirebaseSocialConfiguration,
  FreeRegistrationPayload,
  MFAChallengeResponse,
  OAuthProviderId,
  User,
} from "@/types";

interface AuthContextValue {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (
    email: string,
    password: string,
  ) => Promise<User | MFAChallengeResponse>;
  completeMfa: (challengeToken: string, code: string) => Promise<User>;
  loginWithSocial: (
    provider: OAuthProviderId,
    configuration: FirebaseSocialConfiguration,
  ) => Promise<User>;
  loginWithPasskey: () => Promise<User>;
  registerFree: (payload: FreeRegistrationPayload) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<User | null>;
  updateUser: (update: Partial<User>) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    try {
      const current = await getCurrentUser();
      setUser(current);
      return current;
    } catch {
      clearSession();
      setUser(null);
      return null;
    }
  }, []);

  useEffect(() => {
    setUser(storedUser());
    void refreshUser().finally(() => setIsLoading(false));
  }, [refreshUser]);

  const login = useCallback(async (email: string, password: string) => {
    const response = await apiLogin(email, password);
    if ("mfa_required" in response) return response;
    setUser(response.user);
    return response.user;
  }, []);

  const completeMfa = useCallback(
    async (challengeToken: string, code: string) => {
      const response = await completeMfaLogin(challengeToken, code);
      setUser(response.user);
      return response.user;
    },
    [],
  );

  const loginWithSocial = useCallback(
    async (
      provider: OAuthProviderId,
      configuration: FirebaseSocialConfiguration,
    ) => {
      const idToken = await firebaseSocialIdToken(provider, configuration);
      const response = await createFirebaseSocialSession(idToken);
      setUser(response.user);
      return response.user;
    },
    [],
  );

  const loginWithPasskey = useCallback(async () => {
    const response = await authenticateWithPasskey();
    setUser(response.user);
    return response.user;
  }, []);

  const registerFree = useCallback(async (payload: FreeRegistrationPayload) => {
    const response = await apiRegisterFree(payload);
    setUser(response.user);
    return response.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
    }
  }, []);

  const updateUser = useCallback((update: Partial<User>) => {
    setUser((current) => (current ? { ...current, ...update } : current));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: Boolean(user),
      isLoading,
      login,
      completeMfa,
      loginWithSocial,
      loginWithPasskey,
      registerFree,
      logout,
      refreshUser,
      updateUser,
    }),
    [
      isLoading,
      login,
      completeMfa,
      loginWithPasskey,
      loginWithSocial,
      logout,
      refreshUser,
      registerFree,
      updateUser,
      user,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}
