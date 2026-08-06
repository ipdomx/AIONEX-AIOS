"use client";

import {
  CheckCircle2,
  KeyRound,
  Loader2,
  LogOut,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  disableMFA,
  fetchAccountSessions,
  fetchMFAStatus,
  revokeAccountSession,
  startMFASetup,
  verifyMFASetup,
  type AccountSession,
  type MFASetup,
  type MFAStatus,
} from "@/lib/account-settings";

export default function OwnerAccountSecurityManager() {
  const [mfa, setMfa] = useState<MFAStatus | null>(null);
  const [setup, setSetup] = useState<MFASetup | null>(null);
  const [sessions, setSessions] = useState<AccountSession[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);

  const load = useCallback(async () => {
    try {
      const [nextMfa, nextSessions] = await Promise.all([
        fetchMFAStatus(),
        fetchAccountSessions(),
      ]);
      setMfa(nextMfa);
      setSessions(nextSessions);
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof Error
            ? error.message
            : "Account security could not be loaded.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function beginSetup() {
    setBusy(true);
    setNotice(null);
    try {
      setSetup(await startMFASetup());
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof Error ? error.message : "MFA setup failed.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function verifySetup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code") || "");
    setBusy(true);
    setNotice(null);
    try {
      setMfa(await verifyMFASetup(code));
      setSetup(null);
      setNotice({ tone: "success", text: "MFA is enabled." });
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof Error ? error.message : "Invalid verification code.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function disable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setNotice(null);
    try {
      setMfa(
        await disableMFA(
          String(form.get("password") || ""),
          String(form.get("code") || ""),
        ),
      );
      setSetup(null);
      setNotice({
        tone: "success",
        text: "MFA is disabled and existing sessions were revoked.",
      });
      event.currentTarget.reset();
      setSessions(await fetchAccountSessions());
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof Error ? error.message : "MFA could not be disabled.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function revoke(sessionId: string) {
    setBusy(true);
    setNotice(null);
    try {
      await revokeAccountSession(sessionId);
      setSessions((current) =>
        current.map((item) =>
          item.id === sessionId
            ? { ...item, active: false, revoked_at: new Date().toISOString() }
            : item,
        ),
      );
      setNotice({ tone: "success", text: "Session revoked." });
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof Error
            ? error.message
            : "Session could not be revoked.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      {notice && (
        <div
          role="status"
          className={`flex items-start gap-2 rounded-xl border px-4 py-3 text-sm ${
            notice.tone === "success"
              ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-200"
              : "border-red-500/20 bg-red-500/10 text-red-200"
          }`}
        >
          {notice.tone === "success" ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
          )}
          <span>{notice.text}</span>
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-2">
        <section className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-5">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-electric-300" />
            <h3 className="font-medium text-white">
              Multi-factor authentication
            </h3>
          </div>
          <p className="mt-2 text-xs leading-6 text-white/40">
            {mfa?.enabled
              ? `Enabled with ${mfa.backup_codes_remaining} recovery codes remaining.`
              : "Require a time-based or recovery code after the Owner password."}
          </p>

          {!mfa?.enabled && !setup && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void beginSetup()}
              className="btn-primary mt-4 disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Enable MFA
            </button>
          )}

          {setup && (
            <div className="mt-5 space-y-4">
              <p className="text-xs leading-6 text-white/45">
                Add this secret or provisioning URI to an authenticator, store
                the recovery codes securely, then verify one generated code.
              </p>
              <div className="break-all rounded-lg bg-black/20 p-3 font-mono text-xs text-electric-200">
                {setup.secret}
              </div>
              <div className="break-all rounded-lg bg-black/20 p-3 font-mono text-[10px] text-white/45">
                {setup.qr_code}
              </div>
              <div className="grid grid-cols-2 gap-2">
                {setup.backup_codes.map((code) => (
                  <code
                    key={code}
                    className="rounded-lg bg-black/20 p-2 text-center text-xs text-white/70"
                  >
                    {code}
                  </code>
                ))}
              </div>
              <form onSubmit={verifySetup} className="flex gap-2">
                <input
                  name="code"
                  required
                  minLength={6}
                  maxLength={32}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="Verification code"
                  className="glass-input min-w-0 flex-1 rounded-xl px-3 py-2 text-sm text-white"
                />
                <button disabled={busy} className="btn-primary px-4">
                  Verify
                </button>
              </form>
            </div>
          )}

          {mfa?.enabled && (
            <form onSubmit={disable} className="mt-5 grid gap-3 sm:grid-cols-2">
              <input
                name="password"
                type="password"
                required
                autoComplete="current-password"
                placeholder="Current password"
                className="glass-input rounded-xl px-3 py-2 text-sm text-white"
              />
              <input
                name="code"
                required
                minLength={6}
                maxLength={32}
                placeholder="Verification or recovery code"
                className="glass-input rounded-xl px-3 py-2 text-sm text-white"
              />
              <button
                disabled={busy}
                className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-2 text-sm text-red-300 sm:col-span-2 disabled:opacity-50"
              >
                Disable MFA and revoke sessions
              </button>
            </form>
          )}
        </section>

        <section className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-5">
          <div className="flex items-center gap-2">
            <LogOut className="h-4 w-4 text-electric-300" />
            <h3 className="font-medium text-white">Account sessions</h3>
          </div>
          <div className="mt-4 max-h-96 space-y-2 overflow-y-auto">
            {sessions.map((session) => (
              <div key={session.id} className="rounded-xl bg-black/15 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-xs text-white/70">
                      {session.user_agent || "Unknown device"}
                    </p>
                    <p className="mt-1 text-[11px] text-white/35">
                      {session.ip_address || "Unknown address"} ·{" "}
                      {new Date(session.created_at).toLocaleString()}
                    </p>
                  </div>
                  <span
                    className={`rounded-full px-2 py-1 text-[10px] ${
                      session.active
                        ? "bg-green-500/10 text-green-300"
                        : "bg-white/[0.05] text-white/35"
                    }`}
                  >
                    {session.active ? "Active" : "Closed"}
                  </span>
                </div>
                {session.active && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void revoke(session.id)}
                    className="mt-2 text-xs font-semibold text-red-300 hover:text-red-200 disabled:opacity-50"
                  >
                    Revoke this session
                  </button>
                )}
              </div>
            ))}
            {!sessions.length && (
              <p className="text-xs text-white/35">
                No account sessions recorded.
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
