"use client";

import { ChangeEvent, useEffect, useState } from "react";
import {
  HardDrive,
  KeyRound,
  Loader2,
  MessageSquare,
  ShieldCheck,
  Upload,
  UserRound,
} from "lucide-react";

import { useAuth } from "@/components/providers/AuthProvider";
import {
  changeAccountPassword,
  fetchAccountSettings,
  updateAccountSettings,
  type AccountSettings,
} from "@/lib/account-settings";

const empty: AccountSettings = {
  profile: {
    id: "",
    name: "",
    email: "",
    role: "",
    organization: "",
    avatar: null,
  },
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
  free_tier: null,
};

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(0, Math.round(bytes / 1024))} KB`;
}

function QuotaCard({
  icon: Icon,
  label,
  used,
  limit,
}: {
  icon: typeof HardDrive;
  label: string;
  used: string | number;
  limit: string | number;
}) {
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
      <Icon className="h-5 w-5 text-electric-300" />
      <div className="mt-3 text-xs text-white/40">{label}</div>
      <div className="mt-1 text-lg font-semibold text-white">
        {used} <span className="text-sm font-normal text-white/35">/ {limit}</span>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const { refreshUser } = useAuth();
  const [data, setData] = useState<AccountSettings>(empty);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("Loading profile…");

  useEffect(() => {
    const controller = new AbortController();
    fetchAccountSettings(controller.signal)
      .then((result) => {
        setData(result);
        setMessage("Profile synchronized.");
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setMessage(error instanceof Error ? error.message : "Profile failed");
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  async function handleAvatar(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) {
      setMessage("Use a PNG, JPEG, WebP, or GIF image.");
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      setMessage("Profile image must be no larger than 2 MB.");
      return;
    }

    setBusy(true);
    setMessage("Uploading profile image…");
    try {
      const avatar = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("Unable to read the image."));
        reader.readAsDataURL(file);
      });
      const result = await updateAccountSettings({ avatar });
      setData(result);
      await refreshUser();
      setMessage("Profile image updated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Avatar update failed");
    } finally {
      setBusy(false);
    }
  }

  async function changePassword() {
    if (newPassword !== confirmPassword) {
      setMessage("New passwords do not match.");
      return;
    }
    setBusy(true);
    setMessage("Changing password…");
    try {
      const result = await changeAccountPassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setMessage(result.message);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Password change failed",
      );
    } finally {
      setBusy(false);
    }
  }

  const quota = data.free_tier;
  const limits = quota?.limits;
  const usage = quota?.usage;

  return (
    <div className="space-y-6">
      <div>
        <div className="inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
          <ShieldCheck className="h-3.5 w-3.5" /> Restricted free account
        </div>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-white">
          My profile
        </h1>
        <p className="mt-2 text-sm text-white/45">{message}</p>
      </div>

      {loading ? (
        <div className="glass-card flex min-h-64 items-center justify-center">
          <Loader2 className="h-7 w-7 animate-spin text-electric-300" />
        </div>
      ) : (
        <>
          <section className="glass-card grid gap-6 p-6 md:grid-cols-[180px_1fr]">
            <div className="flex flex-col items-center gap-4">
              <div className="flex h-32 w-32 items-center justify-center overflow-hidden rounded-full border border-white/10 bg-white/[0.04]">
                {data.profile.avatar ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={data.profile.avatar}
                    alt="Profile"
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <UserRound className="h-14 w-14 text-white/25" />
                )}
              </div>
              <label className="btn-primary cursor-pointer">
                <Upload className="h-4 w-4" />
                Change image
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  disabled={busy}
                  onChange={(event) => void handleAvatar(event)}
                  className="hidden"
                />
              </label>
              <span className="text-center text-[11px] text-white/35">
                PNG, JPEG, WebP, or GIF · maximum 2 MB
              </span>
            </div>

            <div className="grid content-start gap-4 sm:grid-cols-2">
              {[
                ["Name", data.profile.name],
                ["Email", data.profile.email],
                ["Account", data.profile.role],
                ["Workspace", data.profile.organization],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="rounded-xl border border-white/[0.06] bg-white/[0.025] p-4"
                >
                  <div className="text-xs text-white/35">{label}</div>
                  <div className="mt-2 break-all text-sm text-white/80">{value}</div>
                </div>
              ))}
              <div className="sm:col-span-2 rounded-xl border border-electric-500/15 bg-electric-500/[0.05] p-4 text-xs leading-5 text-electric-200/80">
                This account can manage one free project, view this profile, change
                its profile image, and change its password. Additional platform
                capabilities require an owner-assigned plan or role.
              </div>
            </div>
          </section>

          {quota?.free_tier && limits && usage && (
            <section className="glass-card p-6">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-white">Free-plan usage</h2>
                  <p className="mt-1 text-xs text-white/35">
                    Limits are configured by the platform owner.
                  </p>
                </div>
                {quota.period_ends_at && (
                  <div className="rounded-lg border border-white/[0.06] px-3 py-2 text-xs text-white/45">
                    Resets {new Date(quota.period_ends_at).toLocaleDateString()}
                  </div>
                )}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <QuotaCard
                  icon={UserRound}
                  label="Projects"
                  used={usage.projects}
                  limit={limits.projects}
                />
                <QuotaCard
                  icon={MessageSquare}
                  label="Your messages"
                  used={usage.user_messages}
                  limit={limits.user_messages}
                />
                <QuotaCard
                  icon={MessageSquare}
                  label="AI replies"
                  used={usage.assistant_responses}
                  limit={limits.assistant_responses}
                />
                <QuotaCard
                  icon={HardDrive}
                  label="Storage"
                  used={formatBytes(usage.storage_bytes)}
                  limit={formatBytes(limits.storage_bytes)}
                />
              </div>
            </section>
          )}

          <section className="glass-card p-6">
            <div className="flex items-center gap-3">
              <KeyRound className="h-5 w-5 text-electric-300" />
              <div>
                <h2 className="text-lg font-semibold text-white">Change password</h2>
                <p className="text-xs text-white/35">
                  All active refresh sessions are revoked after a successful change.
                </p>
              </div>
            </div>
            <div className="mt-5 grid gap-3 lg:grid-cols-3">
              <input
                type="password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                placeholder="Current password"
                autoComplete="current-password"
                className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none"
              />
              <input
                type="password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                placeholder={`New password (${data.security.password_min_length}+ characters)`}
                autoComplete="new-password"
                className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none"
              />
              <input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder="Confirm new password"
                autoComplete="new-password"
                className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none"
              />
            </div>
            <button
              type="button"
              disabled={
                busy ||
                !currentPassword ||
                newPassword.length < data.security.password_min_length ||
                !confirmPassword
              }
              onClick={() => void changePassword()}
              className="btn-primary mt-4 disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Change password
            </button>
          </section>
        </>
      )}
    </div>
  );
}
