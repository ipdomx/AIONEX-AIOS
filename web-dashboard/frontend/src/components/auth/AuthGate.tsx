"use client";

import { FormEvent, PropsWithChildren, useEffect, useState } from "react";
import { AlertTriangle, Loader2, LockKeyhole, ShieldCheck } from "lucide-react";

import { useAuth } from "@/components/providers/AuthProvider";

const USER_PORTAL_URL = (
  process.env.NEXT_PUBLIC_USER_PORTAL_URL || "https://ai.vip-e.net"
).replace(/\/$/, "");

function LoadingScreen({ label }: { label: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-obsidian-950 text-white">
      <Loader2
        className="h-8 w-8 animate-spin text-crimson-400"
        aria-label={label}
      />
    </div>
  );
}

export default function AuthGate({ children }: PropsWithChildren) {
  const { authenticated, completeMfa, loading, login, logout, user } =
    useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [mfaChallenge, setMfaChallenge] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  const unauthorizedRole = authenticated && user?.role !== "Super Owner";

  useEffect(() => {
    if (!loading && unauthorizedRole) {
      void logout().finally(() => {
        window.location.replace(`${USER_PORTAL_URL}/ar/login`);
      });
    }
  }, [loading, logout, unauthorizedRole]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const challenge = await login(email.trim(), password);
      if (challenge) {
        setMfaChallenge(challenge.challenge_token);
        setPassword("");
      }
    } catch (loginError) {
      setError(
        loginError instanceof Error ? loginError.message : "Unable to sign in",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await completeMfa(mfaChallenge, mfaCode);
    } catch (mfaError) {
      setError(
        mfaError instanceof Error
          ? mfaError.message
          : "Unable to verify the security code",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (loading || unauthorizedRole) {
    return <LoadingScreen label="Restoring private session" />;
  }
  if (authenticated) return <>{children}</>;

  return (
    <main className="hero-grid relative isolate flex min-h-screen items-center justify-center overflow-hidden bg-obsidian-950 px-4 py-10 text-white">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-[18%] -z-10 h-[420px] w-[720px] max-w-full -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,rgba(225,29,46,0.12),transparent)]"
      />
      <section className="card-accent w-full max-w-md rounded-3xl border border-white/10 bg-obsidian-800 p-6 shadow-[0_32px_80px_-24px_rgba(0,0,0,0.9)] sm:p-8">
        <div className="mb-7 flex items-center gap-3">
          <div className="brand-mark h-12 w-12">
            <ShieldCheck className="h-6 w-6 text-white" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.25em] text-white/55">
              AIONE<span className="brand-x">X</span> AIOS
            </p>
            <h1 className="text-2xl font-bold">Private control plane</h1>
          </div>
        </div>

        {mfaChallenge ? (
          <form className="space-y-5" onSubmit={handleMfa}>
            <label className="block space-y-2">
              <span className="text-sm text-white/70">
                Verification or recovery code
              </span>
              <input
                type="text"
                inputMode="numeric"
                value={mfaCode}
                onChange={(event) => setMfaCode(event.target.value)}
                autoComplete="one-time-code"
                minLength={6}
                maxLength={32}
                required
                autoFocus
                className="glass-input w-full px-4 py-3 text-white"
              />
            </label>
            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
              >
                <AlertTriangle
                  className="mt-0.5 h-4 w-4 shrink-0 text-rose-400"
                  aria-hidden="true"
                />
                <span>{error}</span>
              </div>
            )}
            <button
              type="submit"
              disabled={submitting || mfaCode.length < 6}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-crimson-500 px-4 py-3 font-semibold text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.12)] transition duration-150 hover:bg-crimson-400 hover:shadow-[0_6px_22px_-6px_rgba(225,29,46,0.6)] active:bg-crimson-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <LockKeyhole className="h-4 w-4" />
              )}
              {submitting ? "Verifying…" : "Verify and continue"}
            </button>
            <button
              type="button"
              onClick={() => {
                setMfaChallenge("");
                setMfaCode("");
                setError(null);
              }}
              className="w-full text-sm text-white/45 hover:text-white"
            >
              Use a different account
            </button>
          </form>
        ) : (
          <form className="space-y-5" onSubmit={handleLogin}>
            <label className="block space-y-2">
              <span className="text-sm text-white/70">Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="username"
                required
                className="glass-input w-full px-4 py-3 text-white"
              />
            </label>
            <label className="block space-y-2">
              <span className="text-sm text-white/70">Password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
                className="glass-input w-full px-4 py-3 text-white"
              />
            </label>

            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
              >
                <AlertTriangle
                  className="mt-0.5 h-4 w-4 shrink-0 text-rose-400"
                  aria-hidden="true"
                />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-crimson-500 px-4 py-3 font-semibold text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.12)] transition duration-150 hover:bg-crimson-400 hover:shadow-[0_6px_22px_-6px_rgba(225,29,46,0.6)] active:bg-crimson-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <LockKeyhole className="h-4 w-4" />
              )}
              {submitting ? "Verifying…" : "Continue"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
