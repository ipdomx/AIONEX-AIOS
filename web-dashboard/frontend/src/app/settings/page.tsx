"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  Bell,
  CreditCard,
  Database,
  Globe,
  Key,
  Palette,
  Settings,
  Shield,
  User,
} from "lucide-react";

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
    language: "en",
    timezone: "UTC",
    theme: "dark",
    email_notifications: true,
    push_notifications: false,
  },
  security: {
    mfa_policy_enabled: false,
    active_sessions: 0,
    password_min_length: 12,
  },
};

export default function SettingsPage() {
  const [active, setActive] =
    useState<(typeof sections)[number]["id"]>("profile");
  const [data, setData] = useState<AccountSettings>(empty);
  const [name, setName] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
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
    setBusy(true);
    try {
      const result = await changeAccountPassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setData((current) => ({
        ...current,
        security: { ...current.security, active_sessions: 0 },
      }));
      setMessage(result.message);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Password change failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function revokeSessions() {
    setBusy(true);
    try {
      const result = await revokeAccountSessions();
      setData((current) => ({
        ...current,
        security: { ...current.security, active_sessions: 0 },
      }));
      setMessage(`Revoked ${result.revoked} refresh session(s).`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Session revoke failed",
      );
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
              <h2 className="text-lg font-semibold text-white">Security</h2>
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 text-sm text-white/60">
                MFA deployment flag:{" "}
                {data.security.mfa_policy_enabled ? "Enabled" : "Disabled"}.
                This settings contract does not assert sign-in enforcement.
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  placeholder="Current password"
                  className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
                />
                <input
                  type="password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  placeholder={`New password (${data.security.password_min_length}+ characters)`}
                  className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
                />
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  disabled={
                    busy ||
                    !currentPassword ||
                    newPassword.length < data.security.password_min_length
                  }
                  onClick={() => void changePassword()}
                  className="btn-primary disabled:opacity-50"
                >
                  Change password
                </button>
                <button
                  disabled={busy || data.security.active_sessions === 0}
                  onClick={() => void revokeSessions()}
                  className="rounded-xl border border-orange-500/20 bg-orange-500/10 px-4 py-2 text-sm text-orange-300 disabled:opacity-50"
                >
                  Revoke {data.security.active_sessions} session(s)
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
                  onChange={(event) =>
                    void save(
                      { language: event.target.value },
                      "Language saved.",
                    )
                  }
                  className="glass-input w-full rounded-xl px-4 py-2.5 text-sm text-white"
                >
                  <option value="en" className="bg-space-800">
                    English
                  </option>
                  <option value="ar" className="bg-space-800">
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
