"use client";

import { FormEvent, PropsWithChildren, useEffect, useMemo, useState } from "react";
import {
  Cookie,
  HardDrive,
  Loader2,
  LogIn,
  MessageSquare,
  ShieldCheck,
  UserPlus,
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "@/components/providers/AuthProvider";
import {
  authService,
  collectRegistrationTelemetry,
  type FreeTierPublicPolicy,
} from "@/lib/auth-service";

const FREE_ALLOWED_PREFIXES = ["/projects", "/profile"];

function inferredCountryCode(): string {
  if (typeof navigator === "undefined") return "";
  const locale = navigator.language.replace("_", "-");
  const segments = locale.split("-");
  const region = segments.find((segment) => /^[A-Za-z]{2}$/.test(segment));
  return region?.toUpperCase() ?? "";
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

function LoadingScreen({ label }: { label: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-space-950 text-white">
      <Loader2
        className="h-8 w-8 animate-spin text-electric-400"
        aria-label={label}
      />
    </div>
  );
}

export default function AuthGate({ children }: PropsWithChildren) {
  const { authenticated, loading, login, registerFree, user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [loginEmail, setLoginEmail] = useState("owner@aionex.local");
  const [loginPassword, setLoginPassword] = useState("");
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [phoneVerificationToken, setPhoneVerificationToken] = useState("");
  const [registrationEmail, setRegistrationEmail] = useState("");
  const [registrationPassword, setRegistrationPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [countryCode, setCountryCode] = useState("");
  const [consentAccepted, setConsentAccepted] = useState(false);
  const [policy, setPolicy] = useState<FreeTierPublicPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isFreeUser = user?.role === "Free User";
  const freeRouteAllowed = useMemo(
    () => FREE_ALLOWED_PREFIXES.some((prefix) => pathname.startsWith(prefix)),
    [pathname],
  );

  useEffect(() => {
    setCountryCode((current) => current || inferredCountryCode());
    let cancelled = false;
    authService
      .getPublicFreeTierPolicy()
      .then((result) => {
        if (!cancelled) setPolicy(result);
      })
      .catch((policyError: unknown) => {
        if (!cancelled) {
          setError(
            policyError instanceof Error
              ? policyError.message
              : "Free registration is temporarily unavailable.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setPolicyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!loading && authenticated && isFreeUser && !freeRouteAllowed) {
      router.replace(pathname === "/" ? "/projects" : "/profile");
    }
  }, [authenticated, freeRouteAllowed, isFreeUser, loading, pathname, router]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(loginEmail.trim(), loginPassword);
    } catch (loginError) {
      setError(
        loginError instanceof Error ? loginError.message : "Unable to sign in",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRegistration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!policy?.enabled) {
      setError("Free registration is currently disabled by the platform owner.");
      return;
    }
    if (!/^[A-Za-z0-9_.-]{3,32}$/.test(username.trim())) {
      setError("Username must contain 3-32 letters, numbers, dots, dashes, or underscores.");
      return;
    }
    if (!birthDate) {
      setError("Date of birth is required.");
      return;
    }
    const birth = new Date(`${birthDate}T00:00:00Z`);
    const today = new Date();
    let age = today.getUTCFullYear() - birth.getUTCFullYear();
    const beforeBirthday =
      today.getUTCMonth() < birth.getUTCMonth() ||
      (today.getUTCMonth() === birth.getUTCMonth() &&
        today.getUTCDate() < birth.getUTCDate());
    if (beforeBirthday) age -= 1;
    if (!Number.isFinite(age) || age < (policy.identity?.minimum_age ?? 18)) {
      setError(`You must be at least ${policy.identity?.minimum_age ?? 18} years old.`);
      return;
    }
    if (!/^\+[1-9][0-9]{7,14}$/.test(phoneNumber.trim())) {
      setError("Enter a verified mobile number in international format, such as +971501234567.");
      return;
    }
    if (
      policy.identity?.phone_verification_required &&
      phoneVerificationToken.trim().length < 24
    ) {
      setError("Complete mobile-number verification before creating the account.");
      return;
    }
    if (registrationPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (registrationPassword.length < 12) {
      setError("Password must contain at least 12 characters.");
      return;
    }
    if (!/^[A-Za-z]{2}$/.test(countryCode.trim())) {
      setError("Enter your two-letter country code, such as AE or EG.");
      return;
    }
    if (!consentAccepted) {
      setError("Consent is required to create a free account.");
      return;
    }

    const telemetry = collectRegistrationTelemetry();
    if (policy.identity?.device_signals_required && telemetry.cookie_enabled !== true) {
      setError("Required cookies must be enabled before registration.");
      return;
    }

    setSubmitting(true);
    try {
      await registerFree({
        username: username.trim().toLowerCase(),
        name: name.trim(),
        email: registrationEmail.trim(),
        password: registrationPassword,
        birth_date: birthDate,
        country_code: countryCode.trim().toUpperCase(),
        phone_number: phoneNumber.trim(),
        phone_verification_token: phoneVerificationToken.trim(),
        consent_accepted: true,
        consent_version: policy.consent_version,
        telemetry,
      });
      router.replace("/projects");
    } catch (registrationError) {
      setError(
        registrationError instanceof Error
          ? registrationError.message
          : "Unable to create the free account.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <LoadingScreen label="Loading session" />;
  if (authenticated && isFreeUser && !freeRouteAllowed) {
    return <LoadingScreen label="Opening free account" />;
  }
  if (authenticated) return <>{children}</>;

  return (
    <main className="flex min-h-screen items-center justify-center bg-space-950 px-4 py-10 text-white">
      <section
        className={`w-full rounded-3xl border border-white/10 bg-white/[0.04] p-6 shadow-2xl backdrop-blur-xl sm:p-8 ${
          mode === "register" ? "max-w-2xl" : "max-w-md"
        }`}
      >
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-electric-500/15 text-electric-300">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-white/40">
              AIONEX AIOS
            </p>
            <h1 className="text-2xl font-semibold">
              {mode === "login" ? "Sign in" : "Create a free account"}
            </h1>
          </div>
        </div>

        <div className="mb-6 grid grid-cols-2 rounded-xl border border-white/10 bg-black/20 p-1">
          <button
            type="button"
            onClick={() => {
              setMode("login");
              setError(null);
            }}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
              mode === "login"
                ? "bg-electric-500 text-white"
                : "text-white/50 hover:text-white"
            }`}
          >
            Owner / member sign in
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("register");
              setError(null);
            }}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
              mode === "register"
                ? "bg-electric-500 text-white"
                : "text-white/50 hover:text-white"
            }`}
          >
            Free user registration
          </button>
        </div>

        {mode === "login" ? (
          <form className="space-y-5" onSubmit={handleLogin}>
            <label className="block space-y-2">
              <span className="text-sm text-white/70">Email</span>
              <input
                type="email"
                value={loginEmail}
                onChange={(event) => setLoginEmail(event.target.value)}
                autoComplete="username"
                required
                className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none transition focus:border-electric-400/60 focus:ring-2 focus:ring-electric-400/20"
              />
            </label>
            <label className="block space-y-2">
              <span className="text-sm text-white/70">Password</span>
              <input
                type="password"
                value={loginPassword}
                onChange={(event) => setLoginPassword(event.target.value)}
                autoComplete="current-password"
                required
                className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none transition focus:border-electric-400/60 focus:ring-2 focus:ring-electric-400/20"
              />
            </label>
            {error && (
              <div
                role="alert"
                className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200"
              >
                {error}
              </div>
            )}
            <button
              type="submit"
              disabled={submitting}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-electric-500 px-4 py-3 font-semibold text-white transition hover:bg-electric-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <LogIn className="h-4 w-4" />
              )}
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </form>
        ) : (
          <form className="space-y-5" onSubmit={handleRegistration}>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-2">
                <span className="text-sm text-white/70">Username</span>
                <input
                  value={username}
                  onChange={(event) =>
                    setUsername(
                      event.target.value
                        .replace(/[^A-Za-z0-9_.-]/g, "")
                        .slice(0, 32),
                    )
                  }
                  autoComplete="username"
                  minLength={3}
                  maxLength={32}
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-white/70">Full name</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  autoComplete="name"
                  minLength={2}
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-white/70">Email</span>
                <input
                  type="email"
                  value={registrationEmail}
                  onChange={(event) => setRegistrationEmail(event.target.value)}
                  autoComplete="email"
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-white/70">Date of birth</span>
                <input
                  type="date"
                  value={birthDate}
                  onChange={(event) => setBirthDate(event.target.value)}
                  autoComplete="bday"
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-white/70">Mobile number</span>
                <input
                  type="tel"
                  value={phoneNumber}
                  onChange={(event) =>
                    setPhoneNumber(
                      event.target.value.replace(/[^+0-9]/g, "").slice(0, 16),
                    )
                  }
                  placeholder="+971501234567"
                  autoComplete="tel"
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <label className="space-y-2 sm:col-span-2">
                <span className="text-sm text-white/70">
                  Phone verification assertion
                </span>
                <input
                  value={phoneVerificationToken}
                  onChange={(event) => setPhoneVerificationToken(event.target.value)}
                  autoComplete="one-time-code"
                  minLength={24}
                  required={policy?.identity?.phone_verification_required ?? true}
                  placeholder="Issued after OTP and mobile-line verification"
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 font-mono text-xs text-white outline-none focus:border-electric-400/60"
                />
                <span className="block text-[11px] leading-5 text-white/35">
                  Registration fails closed until the configured phone-verification
                  provider confirms a real mobile line; virtual and VoIP numbers are
                  rejected.
                </span>
              </label>
              <label className="space-y-2">
                <span className="text-sm text-white/70">Password</span>
                <input
                  type="password"
                  value={registrationPassword}
                  onChange={(event) => setRegistrationPassword(event.target.value)}
                  autoComplete="new-password"
                  minLength={12}
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-white/70">Confirm password</span>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  autoComplete="new-password"
                  minLength={12}
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <label className="space-y-2 sm:col-span-2">
                <span className="text-sm text-white/70">
                  Country code (required)
                </span>
                <input
                  value={countryCode}
                  onChange={(event) =>
                    setCountryCode(
                      event.target.value.replace(/[^A-Za-z]/g, "").slice(0, 2),
                    )
                  }
                  maxLength={2}
                  placeholder="AE"
                  autoComplete="country"
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 uppercase text-white outline-none focus:border-electric-400/60"
                />
              </label>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-white/[0.07] bg-black/20 p-3 text-xs text-white/60">
                <HardDrive className="mb-2 h-4 w-4 text-electric-300" />
                {policyLoading
                  ? "Loading storage limit…"
                  : `${formatBytes(policy?.limits.storage_bytes ?? 0)} storage`}
              </div>
              <div className="rounded-xl border border-white/[0.07] bg-black/20 p-3 text-xs text-white/60">
                <MessageSquare className="mb-2 h-4 w-4 text-electric-300" />
                {policyLoading
                  ? "Loading message limits…"
                  : `${policy?.limits.user_messages_per_month ?? 0} messages + ${policy?.limits.assistant_responses_per_month ?? 0} replies / month`}
              </div>
              <div className="rounded-xl border border-white/[0.07] bg-black/20 p-3 text-xs text-white/60">
                <UserPlus className="mb-2 h-4 w-4 text-electric-300" />
                {policyLoading
                  ? "Loading project limit…"
                  : `${policy?.limits.projects ?? 0} free project`}
              </div>
            </div>

            <label className="flex items-start gap-3 rounded-xl border border-electric-500/20 bg-electric-500/[0.06] p-4 text-xs leading-5 text-white/60">
              <input
                type="checkbox"
                checked={consentAccepted}
                onChange={(event) => setConsentAccepted(event.target.checked)}
                required
                className="mt-1"
              />
              <span>
                <span className="mb-1 flex items-center gap-2 font-semibold text-white/85">
                  <Cookie className="h-4 w-4 text-electric-300" /> Required privacy and security consent
                </span>
                I accept the terms, privacy notice, and essential cookies. After
                consent, AIONEX records my verified username, date of birth,
                country, protected phone identity, IP address, browser/user agent,
                language, timezone, screen and coarse device capabilities, plus
                network-quality information when the browser provides it. This
                supports identity verification, one-account controls, security,
                quotas, and owner audit. No MAC address, Wi-Fi name, contacts,
                files, or precise GPS location are collected by this web form.
              </span>
            </label>

            {error && (
              <div
                role="alert"
                className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200"
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={
                submitting ||
                policyLoading ||
                !policy?.enabled ||
                !consentAccepted
              }
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-electric-500 px-4 py-3 font-semibold text-white transition hover:bg-electric-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UserPlus className="h-4 w-4" />
              )}
              {submitting ? "Creating account…" : "Create free account"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
