"use client";

import {
  FormEvent,
  PropsWithChildren,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  CheckCircle2,
  Cookie,
  HardDrive,
  Loader2,
  LogIn,
  MessageSquare,
  Send,
  ShieldCheck,
  Smartphone,
  UserPlus,
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "@/components/providers/AuthProvider";
import {
  authService,
  collectRegistrationTelemetry,
  type FirebasePhoneConfiguration,
  type FreeTierPublicPolicy,
} from "@/lib/auth-service";
import {
  completeFirebasePhoneVerification,
  disposeFirebasePhoneChallenge,
  startFirebasePhoneVerification,
  type FirebasePhoneChallenge,
} from "@/lib/firebase-phone-auth";

const FREE_ALLOWED_PREFIXES = ["/projects", "/profile"];

function inferredCountryCode(): string {
  if (typeof navigator === "undefined") return "";

  const locales = Array.from(
    new Set([...(navigator.languages ?? []), navigator.language].filter(Boolean)),
  );
  for (const locale of locales) {
    const normalized = locale.replace("_", "-");
    try {
      const region = new Intl.Locale(normalized).region;
      if (region && /^[A-Za-z]{2}$/.test(region)) {
        return region.toUpperCase();
      }
    } catch {
      const fallbackRegion = normalized
        .split("-")
        .slice(1)
        .find((segment) => /^[A-Za-z]{2}$/.test(segment));
      if (fallbackRegion) return fallbackRegion.toUpperCase();
    }
  }
  return "";
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
  const [firebaseIdToken, setFirebaseIdToken] = useState("");
  const [verifiedPhoneNumber, setVerifiedPhoneNumber] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otpBusy, setOtpBusy] = useState(false);
  const [otpStatus, setOtpStatus] = useState("");
  const phoneChallengeRef = useRef<FirebasePhoneChallenge | null>(null);
  const [registrationEmail, setRegistrationEmail] = useState("");
  const [registrationPassword, setRegistrationPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [countryCode, setCountryCode] = useState("");
  const [consentAccepted, setConsentAccepted] = useState(false);
  const [policy, setPolicy] = useState<FreeTierPublicPolicy | null>(null);
  const [firebasePhone, setFirebasePhone] =
    useState<FirebasePhoneConfiguration | null>(null);
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
    Promise.all([
      authService.getPublicFreeTierPolicy(),
      authService.getFirebasePhoneConfiguration(),
    ])
      .then(([policyResult, firebaseResult]) => {
        if (!cancelled) {
          setPolicy(policyResult);
          setFirebasePhone(firebaseResult);
        }
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

  useEffect(() => {
    return () => disposeFirebasePhoneChallenge(phoneChallengeRef.current);
  }, []);

  function resetPhoneVerification(nextPhoneNumber?: string) {
    disposeFirebasePhoneChallenge(phoneChallengeRef.current);
    phoneChallengeRef.current = null;
    setFirebaseIdToken("");
    setVerifiedPhoneNumber("");
    setVerificationCode("");
    setOtpSent(false);
    setOtpStatus("");
    if (nextPhoneNumber !== undefined) setPhoneNumber(nextPhoneNumber);
  }

  async function sendVerificationCode() {
    setError(null);
    const normalizedPhone = phoneNumber.trim();
    if (!consentAccepted) {
      setError(
        "Accept the required privacy and security consent before sending SMS.",
      );
      return;
    }
    if (!/^\+[1-9][0-9]{7,14}$/.test(normalizedPhone)) {
      setError(
        "Enter a valid mobile number in international format, such as +971501234567.",
      );
      return;
    }
    if (!firebasePhone?.enabled || !firebasePhone.web_config) {
      setError("Firebase phone verification is not ready on this deployment.");
      return;
    }

    setOtpBusy(true);
    setOtpStatus("Running security verification and sending the SMS…");
    disposeFirebasePhoneChallenge(phoneChallengeRef.current);
    phoneChallengeRef.current = null;
    setFirebaseIdToken("");
    setVerifiedPhoneNumber("");
    setVerificationCode("");
    try {
      const challenge = await startFirebasePhoneVerification(
        firebasePhone.web_config,
        normalizedPhone,
        "firebase-phone-recaptcha",
      );
      phoneChallengeRef.current = challenge;
      setOtpSent(true);
      setOtpStatus("Verification code sent. Enter the six-digit code.");
    } catch (verificationError) {
      setOtpSent(false);
      setOtpStatus("");
      setError(
        verificationError instanceof Error
          ? verificationError.message
          : "Unable to send the verification code.",
      );
    } finally {
      setOtpBusy(false);
    }
  }

  async function verifyCode() {
    setError(null);
    const challenge = phoneChallengeRef.current;
    if (!challenge || !/^\d{6}$/.test(verificationCode)) {
      setError("Enter the six-digit code sent to your phone.");
      return;
    }

    setOtpBusy(true);
    setOtpStatus("Verifying the mobile number…");
    try {
      const idToken = await completeFirebasePhoneVerification(
        challenge,
        verificationCode,
      );
      phoneChallengeRef.current = null;
      setFirebaseIdToken(idToken);
      setVerifiedPhoneNumber(challenge.phoneNumber);
      setOtpSent(false);
      setVerificationCode("");
      setOtpStatus("Mobile number verified by Firebase.");
    } catch (verificationError) {
      phoneChallengeRef.current = null;
      setOtpSent(false);
      setOtpStatus("");
      setError(
        verificationError instanceof Error
          ? verificationError.message
          : "Unable to verify the mobile number.",
      );
    } finally {
      setOtpBusy(false);
    }
  }

  async function handleRegistration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!policy?.enabled) {
      setError(
        "Free registration is currently disabled by the platform owner.",
      );
      return;
    }
    if (!/^[A-Za-z0-9_.-]{3,32}$/.test(username.trim())) {
      setError(
        "Username must contain 3-32 letters, numbers, dots, dashes, or underscores.",
      );
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
      setError(
        `You must be at least ${policy.identity?.minimum_age ?? 18} years old.`,
      );
      return;
    }
    if (!/^\+[1-9][0-9]{7,14}$/.test(phoneNumber.trim())) {
      setError(
        "Enter a verified mobile number in international format, such as +971501234567.",
      );
      return;
    }
    if (
      policy.identity?.phone_verification_required &&
      (firebaseIdToken.trim().length < 100 ||
        verifiedPhoneNumber !== phoneNumber.trim())
    ) {
      setError(
        "Complete Firebase mobile-number verification before creating the account.",
      );
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
    if (
      policy.identity?.device_signals_required &&
      telemetry.cookie_enabled !== true
    ) {
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
        firebase_id_token: firebaseIdToken.trim() || undefined,
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
                  onChange={(event) => {
                    const nextPhoneNumber = event.target.value
                      .replace(/[^+0-9]/g, "")
                      .slice(0, 16);
                    if (nextPhoneNumber !== phoneNumber) {
                      resetPhoneVerification(nextPhoneNumber);
                    }
                  }}
                  placeholder="+971501234567"
                  autoComplete="tel"
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <div className="space-y-3 rounded-2xl border border-white/[0.08] bg-black/20 p-4 sm:col-span-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <span className="flex items-center gap-2 text-sm font-medium text-white/80">
                      <Smartphone className="h-4 w-4 text-electric-300" />
                      Firebase mobile verification
                    </span>
                    <span className="mt-1 block text-[11px] leading-5 text-white/35">
                      reCAPTCHA protects the SMS request. The Firebase ID token
                      is verified again by the AIOS backend and is never stored
                      in the browser after registration.
                    </span>
                  </div>
                  {verifiedPhoneNumber === phoneNumber.trim() &&
                  firebaseIdToken ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-green-500/20 bg-green-500/10 px-3 py-1 text-xs text-green-300">
                      <CheckCircle2 className="h-3.5 w-3.5" /> Verified
                    </span>
                  ) : null}
                </div>

                <div className="grid gap-3 sm:grid-cols-[auto_1fr_auto]">
                  <button
                    type="button"
                    disabled={
                      otpBusy ||
                      !consentAccepted ||
                      !firebasePhone?.enabled ||
                      !/^\+[1-9][0-9]{7,14}$/.test(phoneNumber.trim())
                    }
                    onClick={() => void sendVerificationCode()}
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-electric-500/25 bg-electric-500/10 px-4 py-3 text-sm font-medium text-electric-200 transition hover:bg-electric-500/15 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {otpBusy && !otpSent ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                    {firebaseIdToken ? "Send new code" : "Send code"}
                  </button>

                  <input
                    value={verificationCode}
                    onChange={(event) =>
                      setVerificationCode(
                        event.target.value.replace(/[^0-9]/g, "").slice(0, 6),
                      )
                    }
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    disabled={!otpSent || otpBusy}
                    placeholder="6-digit code"
                    className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-center font-mono tracking-[0.35em] text-white outline-none focus:border-electric-400/60 disabled:opacity-45"
                  />

                  <button
                    type="button"
                    disabled={
                      otpBusy || !otpSent || verificationCode.length !== 6
                    }
                    onClick={() => void verifyCode()}
                    className="inline-flex items-center justify-center gap-2 rounded-xl bg-electric-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-electric-400 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {otpBusy && otpSent ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <ShieldCheck className="h-4 w-4" />
                    )}
                    Verify
                  </button>
                </div>

                <div id="firebase-phone-recaptcha" />
                {otpStatus ? (
                  <p className="text-xs text-electric-200/75">{otpStatus}</p>
                ) : null}
                {!firebasePhone?.enabled && !policyLoading ? (
                  <p className="text-xs text-orange-300">
                    Firebase phone verification is not configured on the
                    backend.
                  </p>
                ) : null}
              </div>
              <label className="space-y-2">
                <span className="text-sm text-white/70">Password</span>
                <input
                  type="password"
                  value={registrationPassword}
                  onChange={(event) =>
                    setRegistrationPassword(event.target.value)
                  }
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
                  <Cookie className="h-4 w-4 text-electric-300" /> Required
                  privacy and security consent
                </span>
                I accept the terms, privacy notice, and essential cookies. After
                consent, AIONEX records my verified username, date of birth,
                country, protected phone identity, IP address, browser/user
                agent, language, timezone, screen and coarse device
                capabilities, plus network-quality information when the browser
                provides it. This supports identity verification, one-account
                controls, security, quotas, and owner audit. No MAC address,
                Wi-Fi name, contacts, files, or precise GPS location are
                collected by this web form.
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
                !consentAccepted ||
                Boolean(
                  policy?.identity?.phone_verification_required &&
                  (verifiedPhoneNumber !== phoneNumber.trim() ||
                    !firebaseIdToken),
                )
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
