"use client";

import { FormEvent, PropsWithChildren, useState } from "react";
import { LogIn, Loader2, ShieldCheck } from "lucide-react";

import { useAuth } from "@/components/providers/AuthProvider";

export default function AuthGate({ children }: PropsWithChildren) {
  const { authenticated, loading, login } = useAuth();
  const [email, setEmail] = useState("owner@aionex.local");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "Unable to sign in");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-space-950 text-white">
        <Loader2 className="h-8 w-8 animate-spin text-electric-400" aria-label="Loading session" />
      </div>
    );
  }

  if (authenticated) return <>{children}</>;

  return (
    <main className="min-h-screen bg-space-950 text-white flex items-center justify-center px-4 py-10">
      <section className="w-full max-w-md rounded-3xl border border-white/10 bg-white/[0.04] p-6 shadow-2xl backdrop-blur-xl sm:p-8">
        <div className="mb-7 flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-electric-500/15 text-electric-300">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-white/40">AIONEX AIOS</p>
            <h1 className="text-2xl font-semibold">Owner sign in</h1>
          </div>
        </div>

        <form className="space-y-5" onSubmit={handleSubmit}>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">Email</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              required
              className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none transition focus:border-electric-400/60 focus:ring-2 focus:ring-electric-400/20"
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
              className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none transition focus:border-electric-400/60 focus:ring-2 focus:ring-electric-400/20"
            />
          </label>

          {error && (
            <div role="alert" className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-electric-500 px-4 py-3 font-semibold text-white transition hover:bg-electric-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
