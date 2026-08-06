"use client";

import {
  ArrowRight,
  Fingerprint,
  LoaderCircle,
  LockKeyhole,
  Mail,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { OAuthButtons } from "@/components/auth/oauth-buttons";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import { getPasskeyConfiguration } from "@/lib/api";
import { passkeysSupported } from "@/lib/passkeys";

export function LoginClient() {
  const t = useTranslations("auth");
  const locale = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading, login, completeMfa, loginWithPasskey } =
    useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [passkeySubmitting, setPasskeySubmitting] = useState(false);
  const [passkeyReady, setPasskeyReady] = useState(false);
  const [error, setError] = useState("");
  const [mfaChallenge, setMfaChallenge] = useState("");
  const [mfaCode, setMfaCode] = useState("");

  useEffect(() => {
    if (!isLoading && isAuthenticated) router.replace(`/${locale}/dashboard`);
  }, [isAuthenticated, isLoading, locale, router]);

  useEffect(() => {
    let active = true;
    getPasskeyConfiguration()
      .then((configuration) => {
        if (active)
          setPasskeyReady(configuration.enabled && passkeysSupported());
      })
      .catch(() => {
        if (active) setPasskeyReady(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const result = await login(email, password);
      if ("mfa_required" in result) {
        setMfaChallenge(result.challenge_token);
        setPassword("");
        return;
      }
      router.replace(`/${locale}/dashboard`);
    } catch {
      setError(t("connectionError"));
    } finally {
      setSubmitting(false);
    }
  }

  async function submitMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await completeMfa(mfaChallenge, mfaCode);
      router.replace(`/${locale}/dashboard`);
    } catch {
      setError(t("mfaCodeError"));
    } finally {
      setSubmitting(false);
    }
  }

  async function signInWithPasskey() {
    setError("");
    setPasskeySubmitting(true);
    try {
      await loginWithPasskey();
      router.replace(`/${locale}/dashboard`);
    } catch {
      setError(t("passkeyError"));
    } finally {
      setPasskeySubmitting(false);
    }
  }

  return (
    <section className="section-pad">
      <div className="page-shell grid items-start gap-10 lg:grid-cols-[.8fr_1.2fr] lg:gap-16">
        <div className="lg:sticky lg:top-28">
          <span className="eyebrow">{t("secureAccess")}</span>
          <h1 className="section-title mt-7">{t("loginTitle")}</h1>
          <p className="section-copy mt-5">{t("loginDescription")}</p>
          <div className="mt-8 flex items-start gap-3 rounded-2xl border border-electric-300/15 bg-electric-400/[0.06] p-5 text-sm leading-7 text-white/55">
            <LockKeyhole
              className="mt-1 h-5 w-5 shrink-0 text-electric-200"
              aria-hidden="true"
            />
            {t("securityNote")}
          </div>
        </div>

        <div className="glass-panel rounded-3xl p-6 sm:p-9">
          {mfaChallenge ? (
            <form onSubmit={submitMfa}>
              <label htmlFor="mfa-code" className="field-label">
                {t("mfaCode")}
              </label>
              <input
                id="mfa-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                className="field-control"
                value={mfaCode}
                onChange={(event) => setMfaCode(event.target.value)}
                minLength={6}
                maxLength={32}
                required
                autoFocus
              />
              {error && (
                <StatusMessage tone="error" className="mt-5">
                  {error}
                </StatusMessage>
              )}
              <Button
                type="submit"
                size="lg"
                className="mt-7 w-full"
                disabled={submitting || mfaCode.length < 6}
              >
                {submitting ? t("verifyingMfa") : t("verifyMfa")}
              </Button>
              <button
                type="button"
                className="mt-4 w-full text-sm text-white/50 hover:text-white"
                onClick={() => {
                  setMfaChallenge("");
                  setMfaCode("");
                  setError("");
                }}
              >
                {t("useDifferentAccount")}
              </button>
            </form>
          ) : (
            <form onSubmit={submit}>
              <div>
                <label htmlFor="login-email" className="field-label">
                  {t("email")}
                </label>
                <div className="relative">
                  <Mail
                    className="pointer-events-none absolute start-4 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30"
                    aria-hidden="true"
                  />
                  <input
                    id="login-email"
                    type="email"
                    className="field-control ps-11"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    autoComplete="email"
                    required
                  />
                </div>
              </div>
              <div className="mt-5">
                <label htmlFor="login-password" className="field-label">
                  {t("password")}
                </label>
                <div className="relative">
                  <LockKeyhole
                    className="pointer-events-none absolute start-4 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30"
                    aria-hidden="true"
                  />
                  <input
                    id="login-password"
                    type="password"
                    className="field-control ps-11"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="current-password"
                    required
                  />
                </div>
              </div>
              {error && (
                <StatusMessage tone="error" className="mt-5">
                  {error}
                </StatusMessage>
              )}
              <Button
                type="submit"
                size="lg"
                className="mt-7 w-full"
                disabled={submitting || isLoading}
              >
                {submitting ? t("signingIn") : t("signIn")}
                {!submitting && (
                  <ArrowRight
                    className="h-4 w-4 rtl:rotate-180"
                    aria-hidden="true"
                  />
                )}
              </Button>
            </form>
          )}

          {!mfaChallenge && passkeyReady && (
            <Button
              type="button"
              variant="secondary"
              size="lg"
              className="mt-4 w-full"
              disabled={submitting || passkeySubmitting || isLoading}
              onClick={() => void signInWithPasskey()}
            >
              {passkeySubmitting ? (
                <LoaderCircle
                  className="h-4 w-4 animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <Fingerprint className="h-4 w-4" aria-hidden="true" />
              )}
              {passkeySubmitting
                ? t("passkeySigningIn")
                : t("signInWithPasskey")}
            </Button>
          )}

          {!mfaChallenge && (
            <div className="my-8 flex items-center gap-3 text-xs text-white/30">
              <span className="h-px flex-1 bg-white/[0.07]" />
              {t("socialDivider")}
              <span className="h-px flex-1 bg-white/[0.07]" />
            </div>
          )}
          {!mfaChallenge && <OAuthButtons />}

          {!mfaChallenge && (
            <p className="mt-8 text-center text-sm text-white/45">
              {t("noAccount")}{" "}
              <Link
                href={`/${locale}/register`}
                className="font-semibold text-electric-200 hover:text-electric-100"
              >
                {t("createAccount")}
              </Link>
              <span className="mx-2 text-white/20">·</span>
              <Link
                href={`/${locale}/forgot-password`}
                className="font-semibold text-electric-200 hover:text-electric-100"
              >
                {t("forgotPassword")}
              </Link>
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
