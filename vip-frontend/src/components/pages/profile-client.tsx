"use client";

import { Camera, KeyRound, LoaderCircle, Save, ShieldCheck, UserRound } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { PasskeyManager } from "@/components/auth/passkey-manager";
import { useAuth } from "@/hooks/use-auth";
import { changePassword, getSettings, updateSettings } from "@/lib/api";
import type { AccountSettings } from "@/types";

function errorText(cause: unknown, fallback: string): string {
  void cause;
  return fallback;
}

export function ProfileClient() {
  const t = useTranslations("profile");
  const locale = useLocale();
  const router = useRouter();
  const { user, isAuthenticated, isLoading, logout, updateUser } = useAuth();
  const [settings, setSettings] = useState<AccountSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [avatar, setAvatar] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [profileError, setProfileError] = useState("");
  const [profileSuccess, setProfileSuccess] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  useEffect(() => {
    if (!isAuthenticated) return;
    setLoading(true);
    getSettings()
      .then((result) => {
        setSettings(result);
        setAvatar(result.profile.avatar);
        setName(result.profile.name);
      })
      .catch((cause) => setProfileError(errorText(cause, t("loadError"))))
      .finally(() => setLoading(false));
  }, [isAuthenticated, t]);

  function selectAvatar(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    setProfileError("");
    setProfileSuccess("");
    if (!file) return;
    if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) {
      setProfileError(t("avatarTypeError"));
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      setProfileError(t("avatarSizeError"));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setAvatar(typeof reader.result === "string" ? reader.result : null);
    reader.onerror = () => setProfileError(t("avatarReadError"));
    reader.readAsDataURL(file);
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings) return;
    setProfileError("");
    setProfileSuccess("");
    setSavingProfile(true);
    try {
      const isFree = settings.profile.role === "Free User";
      const result = await updateSettings({
        avatar: avatar || "",
        ...(!isFree && name.trim() !== settings.profile.name ? { name: name.trim() } : {})
      });
      setSettings(result);
      setAvatar(result.profile.avatar);
      setName(result.profile.name);
      updateUser({ name: result.profile.name, avatar: result.profile.avatar });
      setProfileSuccess(t("profileSaved"));
    } catch (cause) {
      setProfileError(errorText(cause, t("saveError")));
    } finally {
      setSavingProfile(false);
    }
  }

  async function savePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const currentPassword = String(form.get("currentPassword") || "");
    const newPassword = String(form.get("newPassword") || "");
    const confirmPassword = String(form.get("confirmPassword") || "");
    setPasswordError("");
    if (newPassword !== confirmPassword) {
      setPasswordError(t("passwordMismatch"));
      return;
    }
    setSavingPassword(true);
    try {
      await changePassword(currentPassword, newPassword);
      await logout().catch(() => undefined);
      router.replace(`/${locale}/login?password=changed`);
    } catch (cause) {
      setPasswordError(errorText(cause, t("passwordError")));
    } finally {
      setSavingPassword(false);
    }
  }

  if (isLoading || loading || !user || !settings) {
    return <div className="page-shell section-pad flex items-center justify-center gap-3 text-white/50"><LoaderCircle className="h-5 w-5 animate-spin" />{t("loading")}</div>;
  }

  const isFree = settings.profile.role === "Free User";
  const initials = settings.profile.name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();

  return (
    <section className="section-pad">
      <div className="page-shell">
        <div className="max-w-3xl">
          <span className="eyebrow"><UserRound className="h-3.5 w-3.5" />{t("eyebrow")}</span>
          <h1 className="section-title mt-7">{t("title")}</h1>
          <p className="section-copy mt-5">{t("description")}</p>
        </div>

        <div className="mt-12 grid gap-6 lg:grid-cols-2">
          <form onSubmit={saveProfile} className="glass-panel rounded-3xl p-6 sm:p-9">
            <div className="flex items-center gap-3">
              <Camera className="h-5 w-5 text-electric-200" aria-hidden="true" />
              <h2 className="text-xl font-semibold">{t("identityTitle")}</h2>
            </div>
            <div className="mt-7 flex flex-col items-start gap-5 sm:flex-row sm:items-center">
              <div className="flex h-24 w-24 shrink-0 items-center justify-center overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-electric-400/15 to-violet-500/15 text-2xl font-bold text-electric-100">
                {avatar ? <Image src={avatar} alt={t("avatarAlt")} width={96} height={96} unoptimized className="h-full w-full object-cover" /> : initials}
              </div>
              <div>
                <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="sr-only" onChange={selectAvatar} />
                <Button variant="secondary" onClick={() => fileInput.current?.click()}>{t("chooseAvatar")}</Button>
                <p className="mt-2 text-xs leading-5 text-white/35">{t("avatarRule")}</p>
              </div>
            </div>
            <div className="mt-7">
              <label htmlFor="profile-name" className="field-label">{t("name")}</label>
              <input id="profile-name" className="field-control" value={name} onChange={(event) => setName(event.target.value)} minLength={2} maxLength={200} disabled={isFree} required />
              {isFree && <p className="mt-2 text-xs text-white/35">{t("freeNameLocked")}</p>}
            </div>
            <div className="mt-5">
              <label htmlFor="profile-email" className="field-label">{t("email")}</label>
              <input id="profile-email" className="field-control" value={settings.profile.email} disabled readOnly />
            </div>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <div className="rounded-xl border border-white/[0.07] p-4">
                <p className="text-xs text-white/35">{t("role")}</p>
                <p className="mt-1 text-sm font-semibold">{settings.profile.role}</p>
              </div>
              <div className="rounded-xl border border-white/[0.07] p-4">
                <p className="text-xs text-white/35">{t("organization")}</p>
                <p className="mt-1 truncate text-sm font-semibold">{settings.profile.organization}</p>
              </div>
            </div>
            {profileError && <StatusMessage tone="error" className="mt-5">{profileError}</StatusMessage>}
            {profileSuccess && <StatusMessage tone="success" className="mt-5">{profileSuccess}</StatusMessage>}
            <Button type="submit" className="mt-7" disabled={savingProfile}>
              {savingProfile ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {savingProfile ? t("saving") : t("saveProfile")}
            </Button>
          </form>

          <form onSubmit={savePassword} className="glass-panel rounded-3xl p-6 sm:p-9">
            <div className="flex items-center gap-3">
              <KeyRound className="h-5 w-5 text-violet-400" aria-hidden="true" />
              <h2 className="text-xl font-semibold">{t("passwordTitle")}</h2>
            </div>
            <p className="mt-3 text-sm leading-7 text-white/45">{t("passwordDescription")}</p>
            <div className="mt-7">
              <label htmlFor="current-password" className="field-label">{t("currentPassword")}</label>
              <input id="current-password" name="currentPassword" type="password" className="field-control" autoComplete="current-password" required />
            </div>
            <div className="mt-5">
              <label htmlFor="new-password" className="field-label">{t("newPassword")}</label>
              <input id="new-password" name="newPassword" type="password" className="field-control" minLength={settings.security.password_min_length} maxLength={256} autoComplete="new-password" required />
              <p className="mt-2 text-xs text-white/35">{t("passwordMinimum", { count: settings.security.password_min_length })}</p>
            </div>
            <div className="mt-5">
              <label htmlFor="confirm-new-password" className="field-label">{t("confirmPassword")}</label>
              <input id="confirm-new-password" name="confirmPassword" type="password" className="field-control" minLength={settings.security.password_min_length} maxLength={256} autoComplete="new-password" required />
            </div>
            <div className="mt-6 flex items-start gap-3 rounded-xl border border-electric-300/15 bg-electric-400/[0.06] p-4 text-xs leading-6 text-white/45">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-electric-200" aria-hidden="true" />
              {t("sessionNotice", { count: settings.security.active_sessions })}
            </div>
            {passwordError && <StatusMessage tone="error" className="mt-5">{passwordError}</StatusMessage>}
            <Button type="submit" className="mt-7" disabled={savingPassword}>
              {savingPassword ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
              {savingPassword ? t("updatingPassword") : t("updatePassword")}
            </Button>
          </form>

          <PasskeyManager />
        </div>
      </div>
    </section>
  );
}
