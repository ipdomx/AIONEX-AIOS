"use client";

import {
  KeyRound,
  LoaderCircle,
  LogOut,
  ShieldCheck,
  Smartphone,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import {
  disableMfa,
  getMfaStatus,
  listAccountSessions,
  revokeAccountSession,
  startMfaSetup,
  verifyMfaSetup,
} from "@/lib/api";
import type { AccountSession, MFASetup, MFAStatus } from "@/types";

export function AccountSecurityManager() {
  const t = useTranslations("profile");
  const [mfa, setMfa] = useState<MFAStatus | null>(null);
  const [setup, setSetup] = useState<MFASetup | null>(null);
  const [sessions, setSessions] = useState<AccountSession[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [nextMfa, nextSessions] = await Promise.all([
        getMfaStatus(),
        listAccountSessions(),
      ]);
      setMfa(nextMfa);
      setSessions(nextSessions);
    } catch {
      setError(t("securityLoadError"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function beginSetup() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setSetup(await startMfaSetup());
    } catch {
      setError(t("mfaSetupError"));
    } finally {
      setBusy(false);
    }
  }

  async function verifySetup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code") || "");
    setBusy(true);
    setError("");
    try {
      const result = await verifyMfaSetup(code);
      setMfa(result);
      setSetup(null);
      setMessage(t("mfaEnabled"));
    } catch {
      setError(t("mfaCodeError"));
    } finally {
      setBusy(false);
    }
  }

  async function disable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const result = await disableMfa(
        String(form.get("password") || ""),
        String(form.get("code") || ""),
      );
      setMfa(result);
      setMessage(t("mfaDisabled"));
      event.currentTarget.reset();
    } catch {
      setError(t("mfaDisableError"));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(sessionId: string) {
    setBusy(true);
    setError("");
    try {
      await revokeAccountSession(sessionId);
      setSessions((current) =>
        current.map((item) =>
          item.id === sessionId
            ? { ...item, active: false, revoked_at: new Date().toISOString() }
            : item,
        ),
      );
      setMessage(t("sessionRevoked"));
    } catch {
      setError(t("sessionRevokeError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="glass-panel rounded-3xl p-6 sm:p-9 lg:col-span-2">
      <div className="flex items-center gap-3">
        <ShieldCheck className="h-5 w-5 text-electric-200" />
        <h2 className="text-xl font-semibold">{t("accountSecurityTitle")}</h2>
      </div>
      <p className="mt-3 text-sm leading-7 text-white/45">
        {t("accountSecurityDescription")}
      </p>

      {message && (
        <StatusMessage tone="success" className="mt-5">
          {message}
        </StatusMessage>
      )}
      {error && (
        <StatusMessage tone="error" className="mt-5">
          {error}
        </StatusMessage>
      )}

      <div className="mt-7 grid gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/[0.07] p-5">
          <div className="flex items-center gap-2">
            <Smartphone className="h-4 w-4 text-violet-300" />
            <h3 className="font-semibold">{t("mfaTitle")}</h3>
          </div>
          <p className="mt-2 text-xs leading-6 text-white/40">
            {mfa?.enabled
              ? t("mfaActive", { count: mfa.backup_codes_remaining })
              : t("mfaInactive")}
          </p>
          {!mfa?.enabled && !setup && (
            <Button
              className="mt-4"
              disabled={busy}
              onClick={() => void beginSetup()}
            >
              {busy ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <KeyRound className="h-4 w-4" />
              )}
              {t("enableMfa")}
            </Button>
          )}
          {setup && (
            <div className="mt-4 space-y-4">
              <div className="rounded-xl bg-black/20 p-3 font-mono text-xs text-electric-100 break-all">
                {setup.secret}
              </div>
              <div>
                <p className="text-xs text-white/45">{t("backupCodes")}</p>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {setup.backup_codes.map((code) => (
                    <code
                      key={code}
                      className="rounded-lg bg-black/20 p-2 text-center text-xs text-white/70"
                    >
                      {code}
                    </code>
                  ))}
                </div>
              </div>
              <form onSubmit={verifySetup} className="flex gap-2">
                <input
                  name="code"
                  required
                  minLength={6}
                  maxLength={32}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder={t("mfaCode")}
                  className="field-control min-w-0 flex-1"
                />
                <Button disabled={busy}>{t("verifyMfa")}</Button>
              </form>
            </div>
          )}
          {mfa?.enabled && (
            <form onSubmit={disable} className="mt-4 grid gap-2 sm:grid-cols-2">
              <input
                name="password"
                type="password"
                required
                autoComplete="current-password"
                placeholder={t("currentPassword")}
                className="field-control"
              />
              <input
                name="code"
                required
                minLength={6}
                maxLength={32}
                placeholder={t("mfaCode")}
                className="field-control"
              />
              <Button
                variant="secondary"
                className="sm:col-span-2"
                disabled={busy}
              >
                {t("disableMfa")}
              </Button>
            </form>
          )}
        </div>

        <div className="rounded-2xl border border-white/[0.07] p-5">
          <div className="flex items-center gap-2">
            <LogOut className="h-4 w-4 text-electric-200" />
            <h3 className="font-semibold">{t("sessionsTitle")}</h3>
          </div>
          <div className="mt-4 max-h-80 space-y-2 overflow-y-auto">
            {sessions.map((session) => (
              <div key={session.id} className="rounded-xl bg-white/[0.03] p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-xs text-white/70">
                      {session.user_agent || t("unknownDevice")}
                    </p>
                    <p className="mt-1 text-[11px] text-white/35">
                      {session.ip_address || t("unknownAddress")} ·{" "}
                      {new Date(session.created_at).toLocaleString()}
                    </p>
                  </div>
                  <span
                    className={`rounded-full px-2 py-1 text-[10px] ${session.active ? "bg-green-500/10 text-green-300" : "bg-white/[0.05] text-white/35"}`}
                  >
                    {session.active ? t("activeSession") : t("closedSession")}
                  </span>
                </div>
                {session.active && (
                  <button
                    disabled={busy}
                    onClick={() => void revoke(session.id)}
                    className="mt-2 text-xs font-semibold text-red-300 hover:text-red-200"
                  >
                    {t("revokeSession")}
                  </button>
                )}
              </div>
            ))}
            {!sessions.length && (
              <p className="text-xs text-white/35">{t("noSessions")}</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
