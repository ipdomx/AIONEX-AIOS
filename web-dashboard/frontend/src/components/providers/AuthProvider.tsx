"use client";

import { createContext, PropsWithChildren, useContext, useEffect, useMemo, useState } from "react";

import { AuthUser, authService } from "@/lib/auth-service";

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  authenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export default function AuthProvider({ children }: PropsWithChildren) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      const stored = authService.getStoredUser();
      if (!authService.hasAccessToken()) {
        if (!cancelled) {
          setUser(null);
          setLoading(false);
        }
        return;
      }

      try {
        const current = await authService.currentUser();
        if (!cancelled) setUser(current);
      } catch {
        authService.clearSession();
        if (!cancelled) setUser(stored && authService.hasAccessToken() ? stored : null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void restoreSession();
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      authenticated: Boolean(user),
      async login(email: string, password: string) {
        const response = await authService.login(email, password);
        setUser(response.user);
      },
      async logout() {
        await authService.logout();
        setUser(null);
      },
      async refreshUser() {
        const current = await authService.currentUser();
        setUser(current);
      },
    }),
    [loading, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
