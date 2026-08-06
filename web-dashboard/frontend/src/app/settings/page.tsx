"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  AlertCircle,
  Bell,
  CheckCircle2,
  CreditCard,
  Database,
  Globe,
  Key,
  Loader2,
  Palette,
  Settings,
  Shield,
  User,
} from "lucide-react";

import { useLanguageVoice } from "@/components/providers/LanguageVoiceProvider";
import type { SupportedLocale } from "@/lib/locale-engine";

import OwnerAccountSecurityManager from "@/components/auth/OwnerAccountSecurityManager";

import {
  changeAccountPassword,
  fetchAccountSettings,
  revokeAccountSessions,
  updateAccountSettings,
  type AccountSettings,
} from "@/lib/account-settings";

const sections = [
  { id: "profile", label: "Profile", icon: User },
  { id: "security", label: "Security", icon: Shield },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "language", label: "Language & Region", icon: Globe },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "database", label: "Database", icon: Database },
  { id: "billing", label: "Billing", icon: CreditCard },
  { id: "api", label: "API Keys", icon: Key },
] as const;

const empty: AccountSettings = {
  profile: { id: "", name: "", email: "", role: "", organization: "" },
  preferences: {
    language: "en-US",
    timezone: "UTC",
    theme: "dark",
    email_notifications: true,
    push_notifications: false,
  },
  security: {
    mfa_policy_enabled: false,
    active_sessions: 0,
    password_min_length: 12,
    mfa_enabled: false,
    mfa_backup_codes_remaining: 0,
    passkey_count: 0,
  },
};

export default function SettingsPage() {
  const { setLocale } = useLanguageVoice();
  const [active, setActive] =
    useState<(typeof sections)[number]["id"]>("profile");
  const [data, setData] = useState<AccountSettings>(empty);
  const [name, setName] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [securityNotice, setSecurityNotice] = useState<{
    tone: "success" | "error" | "info";
    text: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading settings...");
  const visibleSections = sections.filter(
    (section) =>
      !["database", "billing", "api"].includes(section.id) ||
      data.profile.role === "Super Owner",
  );

  useEffect(() => {
    const controller = new AbortController();
    fetchAccountSettings(controller.signal)
      .then((result) => {
        setData(result);
        setName(result.profile.name);
        setMessage("Settings synchronized.");
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setMessage(
            error instanceof Error ? error.message : "Settings failed",
          );
        }
      });
    return () => controller.abort();
  }, []);

  async function save(payload: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      const result = await updateAccountSettings(payload);
      setData(result);
      setName(result.profile.name);
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function changePassword() {
    if (newPassword !== confirmPassword) {
      setSecurityNotice({ tone: "error", text: "New passwords do not match." });
      return;
    }
    setBusy(true);
    setSecurityNotice({ tone: "info", text: "Changing password…" });
    try {
      const result = await changeAccountPassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setData((current) => ({
        ...current,
        security: { ...current.security, active_sessions: 0 },
      }));
      setSecurityNotice({ tone: "success", text: result.message });
      setMessage(result.message);
    } catch (error) {
      const detail =
        error instanceof Error ? error.message : "Password change failed";
      setSecurityNotice({ tone: "error", text: detail });
      setMessage(detail);
    } finally {
      setBusy(false);
    }
  }

  async function revokeSessions() {
    setBusy(true);
    setSecurityNotice({ tone: "info", text: "Signing out other sessions…" });
    try {
      const result = await revokeAccountSessions();
      setData((current) => ({
        ...current,
        security: { ...current.security, active_sessions: 0 },
      }));
      const detail = result.revoked
        ? `Revoked ${result.revoked} refresh session(s).`
        : "No other active sessions";
      setSecurityNotice({ tone: "success", text: detail });
      setMessage(detail);
    } catch (error) {
      const detail =
        error instanceof Error ? error.message : "Session revoke failed";
      setSecurityNotice({ tone: "error", text: detail });
      setMessage(detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <h1 className="text-2xl font-bold tracking-tight text-white">
          Settings
        </h1>
        <p className="mt-1 text-sm text-white/40">{message}</p>
      </motion.div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <div className="space-y-1">
          {visibleSections.map((section) => {
            const Icon = section.icon;
            return (
              <button
                key={section.id}
                type="button"
                onClick={() => setActive(section.id)}
                className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm transition ${
                  active === section.id
                    ? "bg-white/[0.08] text-white"
                    : "text-white/50 hover:bg-white/[0.04] hover:text-white/80"
                }`}
              >
                <Icon className="h-[18px] w-[18px]" />
                {section.label}
              </button>
            );
          })}
        </div>

        <section className="glass-card p-6 lg:col-span-3">
          {active === "profile" && (
            <div className="space-y-5">
              <h2 className="text-lg font-semibold text-white">Profile</h2>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-2 text-xs text-white/40">
                  Full name
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    className="glass-input w-full rounded-xl px-4 py-2.5 text-sm text-white outline-none"
                  />
                </label>
                <label className="space-y-2 text-xs text-white/40">
                  Email
                  <input
                    value={data.profile.email}
                    readOnly
                    className="glass-input w-full rounded-xl px-4 py-2.5 text-sm text-white/60 outline-none"
                  />
                </label>
                <div className="rounded-xl bg-white/[0.02] p-4 text-sm text-white/60">
                  Role: {data.profile.role || "—"}
                </div>
                <div className="rounded-xl bg-white/[0.02] p-4 text-sm text-white/60">
                  Organization: {data.profile.organization || "—"}
                </div>
              </div>
              <button
                disabled={busy || name.trim().length < 2}
                onClick={() => void save({ name }, "Profile saved.")}
                className="btn-primary disabled:opacity-50"
              >
                Save changes
              </button>
            </div>
          )}

          {active === "security" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-white">Security</h2>
                <p className="mt-1 text-xs leading-6 text-white/40">
                  This session remains active until the next authenticated
                  request after a password change.
                </p>
              </div>
              <OwnerAccountSecurityManager />
              <div className="grid gap-3 lg:grid-cols-3">
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  placeholder="Current password"
                  autoComplete="current-password"
                  className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
                />
                <input
                  type="password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  placeholder={`New password (${data.security.password_min_length}+ characters)`}
                  autoComplete="new-password"
                  className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
                />
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  placeholder="Confirm new password"
                  autoComplete="new-password"
                  className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
                />
              </div>
              {securityNotice && (
                <div
                  role="status"
                  aria-live="polite"
                  className={`flex items-start gap-2 rounded-xl border px-4 py-3 text-sm ${
                    securityNotice.tone === "success"
                      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-200"
                      : securityNotice.tone === "error"
                        ? "border-red-500/20 bg-red-500/10 text-red-200"
                        : "border-electric-500/20 bg-electric-500/10 text-electric-200"
                  }`}
                >
                  {securityNotice.tone === "success" ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                  ) : securityNotice.tone === "error" ? (
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  ) : (
                    <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
                  )}
                  <span>{securityNotice.text}</span>
                </div>
              )}
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  disabled={
                    busy ||
                    !currentPassword ||
                    newPassword.length < data.security.password_min_length ||
                    !confirmPassword
                  }
                  onClick={() => void changePassword()}
                  className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Change password
                </button>
                <button
                  type="button"
                  disabled={busy || data.security.active_sessions === 0}
                  onClick={() => void revokeSessions()}
                  className="rounded-xl border border-orange-500/20 bg-orange-500/10 px-4 py-2 text-sm text-orange-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {data.security.active_sessions === 0
                    ? "No other active sessions"
                    : "Sign out other sessions"}
                </button>
              </div>
            </div>
          )}

          {active === "notifications" && (
            <div className="space-y-5">
              <h2 className="text-lg font-semibold text-white">
                Notifications
              </h2>
              {(["email_notifications", "push_notifications"] as const).map(
                (key) => (
                  <label
                    key={key}
                    className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 text-sm text-white/65"
                  >
                    {key === "email_notifications"
                      ? "Email notifications"
                      : "Push notifications"}
                    <input
                      type="checkbox"
                      checked={data.preferences[key]}
                      onChange={(event) =>
                        void save(
                          { [key]: event.target.checked },
                          "Notification preference saved.",
                        )
                      }
                    />
                  </label>
                ),
              )}
            </div>
          )}

          {active === "language" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-2 text-xs text-white/40">
                Language
                <select
                  value={data.preferences.language}
                  onChange={(event) => {
                    const language = event.target.value as SupportedLocale;
                    setLocale(language);
                    setData((current) => ({
                      ...current,
                      preferences: { ...current.preferences, language },
                    }));
                    setMessage("Language saved.");
                  }}
                  className="glass-input w-full rounded-xl px-4 py-2.5 text-sm text-white"
                >
                  <option value="en-US" className="bg-space-800">
                    English
                  </option>
                  <option value="ar-AE" className="bg-space-800">
                    العربية
                  </option>
                </select>
              </label>
              <label className="space-y-2 text-xs text-white/40">
                Timezone
                <select
                  value={data.preferences.timezone}
                  onChange={(event) =>
                    void save(
                      { timezone: event.target.value },
                      "Timezone saved.",
                    )
                  }
                  className="glass-input w-full rounded-xl px-4 py-2.5 text-sm text-white"
                >
                  <option value="UTC" className="bg-space-800">
                    UTC
                  </option>
                  <option value="Asia/Dubai" className="bg-space-800">
                    Asia/Dubai
                  </option>
                </select>
              </label>
            </div>
          )}

          {active === "appearance" && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold text-white">Appearance</h2>
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 text-sm text-white/60">
                The production dashboard currently uses its supported dark
                theme.
              </div>
            </div>
          )}

          {active === "database" && (
            <SettingsLink
              href="/owner/health"
              title="Database health"
              description="Open live PostgreSQL and dependency probes."
            />
          )}
          {active === "billing" && (
            <SettingsLink
              href="/owner/billing"
              title="Billing & plans"
              description="Manage organization plans and suspension state."
            />
          )}
          {active === "api" && (
            <SettingsLink
              href="/owner/secrets"
              title="API keys & secret references"
              description="Manage protected external vault references."
            />
          )}
        </section>
      </div>
    </div>
  );
}

function SettingsLink({
  href,
  title,
  description,
}: {
  href: string;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <Settings className="mb-4 h-12 w-12 text-electric-300" />
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <p className="mt-2 text-sm text-white/40">{description}</p>
      <Link href={href} className="btn-primary mt-5">
        Open control
      </Link>
    </div>
  );
}
