"use client";

import { Check, LoaderCircle, Phone, Send, ShieldCheck, UserPlus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { OAuthButtons } from "@/components/auth/oauth-buttons";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  collectRegistrationTelemetry,
  getFirebasePhoneConfiguration,
  getFirebasePhoneReadiness,
  getPublicFreeTierPolicy
} from "@/lib/api";
import {
  completeFirebasePhoneVerification,
  disposeFirebasePhoneChallenge,
  startFirebasePhoneVerification,
  type FirebasePhoneChallenge
} from "@/lib/firebase-phone-auth";
import type {
  FirebasePhoneConfiguration,
  FreeTierPublicPolicy,
  SocialRegistrationPreparation
} from "@/types";

type PhoneStage = "idle" | "sending" | "code" | "confirming" | "verified";

function messageOf(cause: unknown, fallback: string): string {
  void cause;
  return fallback;
}

export function RegisterClient() {
  const t = useTranslations("register");
  const auth = useTranslations("auth");
  const locale = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading, registerFree } = useAuth();
  const [policy, setPolicy] = useState<FreeTierPublicPolicy | null>(null);
  const [phoneConfig, setPhoneConfig] = useState<FirebasePhoneConfiguration | null>(null);
  const [configLoading, setConfigLoading] = useState(true);
  const [configError, setConfigError] = useState("");
  const [phone, setPhone] = useState("");
  const [country, setCountry] = useState("");
  const [phoneStage, setPhoneStage] = useState<PhoneStage>("idle");
  const [challenge, setChallenge] = useState<FirebasePhoneChallenge | null>(null);
  const [verificationCode, setVerificationCode] = useState("");
  const [firebaseIdToken, setFirebaseIdToken] = useState("");
  const [phoneError, setPhoneError] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [socialRegistration, setSocialRegistration] =
    useState<SocialRegistrationPreparation | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const maxBirthDate = useMemo(() => {
    const date = new Date();
    date.setUTCFullYear(date.getUTCFullYear() - (policy?.identity.minimum_age || 18));
    return date.toISOString().slice(0, 10);
  }, [policy]);

  const loadConfiguration = useCallback(async () => {
    setConfigLoading(true);
    setConfigError("");
    try {
      const [nextPolicy, nextPhoneConfig] = await Promise.all([
        getPublicFreeTierPolicy(),
        getFirebasePhoneConfiguration()
      ]);
      setPolicy(nextPolicy);
      setPhoneConfig(nextPhoneConfig);
    } catch (cause) {
      setConfigError(messageOf(cause, t("configurationError")));
    } finally {
      setConfigLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadConfiguration();
  }, [loadConfiguration]);

  useEffect(() => {
    if (!isLoading && isAuthenticated) router.replace(`/${locale}/projects`);
  }, [isAuthenticated, isLoading, locale, router]);

  useEffect(() => () => disposeFirebasePhoneChallenge(challenge), [challenge]);

  function changePhone(value: string) {
    setPhone(value.replace(/[^+0-9]/g, ""));
    if (phoneStage !== "idle") {
      disposeFirebasePhoneChallenge(challenge);
      setChallenge(null);
      setFirebaseIdToken("");
      setVerificationCode("");
      setPhoneStage("idle");
    }
  }

  function useSocialRegistration(value: SocialRegistrationPreparation) {
    setSocialRegistration(value);
    setEmail(value.email);
    if (value.name) setName(value.name);
    setSubmitError("");
  }

  function clearSocialRegistration() {
    setSocialRegistration(null);
    setEmail("");
  }

  async function sendPhoneCode() {
    setPhoneError("");
    if (!/^\+[1-9][0-9]{7,14}$/.test(phone)) {
      setPhoneError(t("phoneFormatError"));
      return;
    }
    if (!phoneConfig?.enabled || !phoneConfig.web_config) {
      setPhoneError(t("phoneUnavailable"));
      return;
    }
    setPhoneStage("sending");
    try {
      const readiness = await getFirebasePhoneReadiness(phone, window.location.origin);
      if (!readiness.ready) throw new Error(readiness.detail || t("phoneUnavailable"));
      disposeFirebasePhoneChallenge(challenge);
      const nextChallenge = await startFirebasePhoneVerification(
        phoneConfig.web_config,
        phone,
        "aionex-phone-recaptcha"
      );
      setChallenge(nextChallenge);
      setPhoneStage("code");
    } catch (cause) {
      setPhoneStage("idle");
      setPhoneError(messageOf(cause, t("phoneSendError")));
    }
  }

  async function confirmPhoneCode() {
    if (!challenge || verificationCode.trim().length < 6) return;
    setPhoneError("");
    setPhoneStage("confirming");
    try {
      const idToken = await completeFirebasePhoneVerification(challenge, verificationCode.trim());
      setFirebaseIdToken(idToken);
      setChallenge(null);
      setPhoneStage("verified");
    } catch (cause) {
      setPhoneStage("code");
      setPhoneError(messageOf(cause, t("phoneConfirmError")));
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!policy) return;
    setSubmitError("");
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") || "");
    const confirmPassword = String(form.get("confirmPassword") || "");
    if (password !== confirmPassword) {
      setSubmitError(t("passwordMismatch"));
      return;
    }
    if (policy.identity.phone_verification_required && !firebaseIdToken) {
      setSubmitError(t("verifyPhoneFirst"));
      return;
    }
    setSubmitting(true);
    try {
      await registerFree({
        username: String(form.get("username") || "").trim(),
        name: String(form.get("name") || "").trim(),
        email: String(form.get("email") || "").trim(),
        password,
        birth_date: String(form.get("birthDate") || ""),
        country_code: country.trim().toUpperCase(),
        phone_number: phone,
        firebase_id_token: firebaseIdToken || undefined,
        social_registration_token:
          socialRegistration?.registration_token || undefined,
        consent_accepted: form.get("consent") === "on",
        consent_version: policy.consent_version,
        telemetry: collectRegistrationTelemetry()
      });
      router.replace(`/${locale}/projects`);
    } catch (cause) {
      setSubmitError(messageOf(cause, t("registrationError")));
    } finally {
      setSubmitting(false);
    }
  }

  if (configLoading) {
    return <div className="page-shell section-pad flex items-center justify-center gap-3 text-white/50"><LoaderCircle className="h-5 w-5 animate-spin" />{t("checkingPolicy")}</div>;
  }

  if (configError || !policy) {
    return (
      <div className="page-shell section-pad max-w-2xl">
        <StatusMessage tone="error">{configError || t("configurationError")}</StatusMessage>
        <Button variant="secondary" className="mt-5" onClick={() => void loadConfiguration()}>{t("retry")}</Button>
      </div>
    );
  }

  if (!policy.enabled) {
    return <div className="page-shell section-pad max-w-2xl"><StatusMessage>{t("registrationClosed")}</StatusMessage></div>;
  }

  const phoneRequired = policy.identity.phone_verification_required;
  const phoneReady = Boolean(phoneConfig?.enabled && phoneConfig.web_config);

  return (
    <section className="section-pad">
      <div className="page-shell grid items-start gap-10 lg:grid-cols-[.72fr_1.28fr] lg:gap-14">
        <aside className="lg:sticky lg:top-28">
          <span className="eyebrow"><UserPlus className="h-3.5 w-3.5" />{t("eyebrow")}</span>
          <h1 className="section-title mt-7">{t("title")}</h1>
          <p className="section-copy mt-5">{t("description")}</p>
          <div className="glass-panel mt-8 rounded-2xl p-5">
            <p className="text-sm font-semibold">{t("currentPolicy")}</p>
            <dl className="mt-4 space-y-3 text-sm text-white/50">
              <div className="flex justify-between gap-4"><dt>{t("projectsLimit")}</dt><dd className="font-semibold text-white">{policy.limits.projects}</dd></div>
              <div className="flex justify-between gap-4"><dt>{t("messagesLimit")}</dt><dd className="font-semibold text-white">{policy.limits.user_messages_per_month}</dd></div>
              <div className="flex justify-between gap-4"><dt>{t("minimumAge")}</dt><dd className="font-semibold text-white">{policy.identity.minimum_age}</dd></div>
            </dl>
            <p className="mt-4 border-t border-white/[0.07] pt-4 text-xs leading-6 text-white/35">{t("ownerControlled")}</p>
          </div>
        </aside>

        <div className="glass-panel rounded-3xl p-6 sm:p-9">
          <OAuthButtons
            mode="register"
            onRegistrationPrepared={useSocialRegistration}
          />
          {socialRegistration && (
            <StatusMessage tone="success" className="mt-5">
              <span>
                {t("socialPrepared", {
                  provider: socialRegistration.provider,
                  email: socialRegistration.email
                })}
              </span>
              <button
                type="button"
                className="ms-auto font-semibold text-electric-100 hover:underline"
                onClick={clearSocialRegistration}
              >
                {t("socialClear")}
              </button>
            </StatusMessage>
          )}
          <div className="my-8 flex items-center gap-3 text-xs text-white/30">
            <span className="h-px flex-1 bg-white/[0.07]" />
            {auth("emailRegistration")}
            <span className="h-px flex-1 bg-white/[0.07]" />
          </div>

          <form onSubmit={submit}>
            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <label htmlFor="register-name" className="field-label">{t("name")}</label>
                <input id="register-name" name="name" className="field-control" value={name} onChange={(event) => setName(event.target.value)} minLength={2} maxLength={200} autoComplete="name" required />
              </div>
              <div>
                <label htmlFor="register-username" className="field-label">{t("username")}</label>
                <input id="register-username" name="username" className="field-control" minLength={3} maxLength={32} pattern="[A-Za-z0-9_.-]+" autoComplete="username" required />
                <p className="mt-2 text-xs text-white/30">{t("usernameRule")}</p>
              </div>
              <div className="sm:col-span-2">
                <label htmlFor="register-email" className="field-label">{t("email")}</label>
                <input id="register-email" name="email" type="email" className="field-control" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" readOnly={Boolean(socialRegistration)} required />
              </div>
              <div>
                <label htmlFor="register-password" className="field-label">{t("password")}</label>
                <input id="register-password" name="password" type="password" className="field-control" minLength={12} maxLength={256} autoComplete="new-password" required />
                <p className="mt-2 text-xs text-white/30">{t("passwordRule")}</p>
              </div>
              <div>
                <label htmlFor="register-confirm-password" className="field-label">{t("confirmPassword")}</label>
                <input id="register-confirm-password" name="confirmPassword" type="password" className="field-control" minLength={12} maxLength={256} autoComplete="new-password" required />
              </div>
              <div>
                <label htmlFor="register-birth" className="field-label">{t("birthDate")}</label>
                <input id="register-birth" name="birthDate" type="date" className="field-control" max={maxBirthDate} required />
              </div>
              <div>
                <label htmlFor="register-country" className="field-label">{t("countryCode")}</label>
                <input id="register-country" name="countryCode" className="field-control uppercase" value={country} onChange={(event) => setCountry(event.target.value.replace(/[^A-Za-z]/g, "").slice(0, 2))} minLength={2} maxLength={2} pattern="[A-Za-z]{2}" autoComplete="country" required />
                <p className="mt-2 text-xs text-white/30">{t("countryRule")}</p>
              </div>
            </div>

            <div className="mt-7 rounded-2xl border border-white/[0.08] bg-black/15 p-5 sm:p-6">
              <div className="flex items-start gap-3">
                <Phone className="mt-0.5 h-5 w-5 shrink-0 text-electric-200" aria-hidden="true" />
                <div>
                  <h2 className="text-sm font-semibold">{t("phoneTitle")}</h2>
                  <p className="mt-1 text-xs leading-6 text-white/40">{phoneRequired ? t("phoneRequired") : t("phoneOptional")}</p>
                </div>
              </div>
              {!phoneReady && phoneRequired && <StatusMessage tone="error" className="mt-4">{t("phoneUnavailable")}</StatusMessage>}
              <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                <input type="tel" className="field-control flex-1" value={phone} onChange={(event) => changePhone(event.target.value)} dir="ltr" autoComplete="tel" pattern="\+[1-9][0-9]{7,14}" required aria-label={t("phoneNumber")} />
                <Button variant="secondary" onClick={() => void sendPhoneCode()} disabled={!phoneReady || phoneStage === "sending" || phoneStage === "confirming" || phoneStage === "verified"}>
                  {phoneStage === "sending" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  {t("sendCode")}
                </Button>
              </div>
              <p className="mt-2 text-xs text-white/30">{t("phoneRule")}</p>
              {(phoneStage === "code" || phoneStage === "confirming") && (
                <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                  <input inputMode="numeric" className="field-control flex-1 tracking-[0.3em]" value={verificationCode} onChange={(event) => setVerificationCode(event.target.value.replace(/\D/g, "").slice(0, 8))} minLength={6} maxLength={8} aria-label={t("verificationCode")} />
                  <Button onClick={() => void confirmPhoneCode()} disabled={phoneStage === "confirming" || verificationCode.length < 6}>
                    {phoneStage === "confirming" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                    {t("confirmCode")}
                  </Button>
                </div>
              )}
              {phoneStage === "verified" && <StatusMessage tone="success" className="mt-4"><ShieldCheck className="h-4 w-4" />{t("phoneVerified")}</StatusMessage>}
              {phoneError && <StatusMessage tone="error" className="mt-4">{phoneError}</StatusMessage>}
              <div id="aionex-phone-recaptcha" />
            </div>

            <label className="mt-6 flex cursor-pointer items-start gap-3 rounded-xl border border-white/[0.07] p-4 text-sm leading-6 text-white/50">
              <input type="checkbox" name="consent" required className="mt-1 h-4 w-4 accent-cyan-400" />
              <span>
                {t("consentLead")} {" "}
                <Link href={`/${locale}/legal/terms`} className="text-electric-200 hover:underline">{t("terms")}</Link>
                {" "}{t("and")}{" "}
                <Link href={`/${locale}/legal/privacy`} className="text-electric-200 hover:underline">{t("privacy")}</Link>. {t("consentData")}
              </span>
            </label>

            {submitError && <StatusMessage tone="error" className="mt-5">{submitError}</StatusMessage>}
            <Button type="submit" size="lg" className="mt-7 w-full" disabled={submitting || (phoneRequired && (!phoneReady || !firebaseIdToken))}>
              {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
              {submitting ? t("creating") : t("createAccount")}
            </Button>
          </form>

          <p className="mt-7 text-center text-sm text-white/45">
            {t("hasAccount")} {" "}
            <Link href={`/${locale}/login`} className="font-semibold text-electric-200 hover:text-electric-100">{t("signIn")}</Link>
          </p>
        </div>
      </div>
    </section>
  );
}
