"use client";

import { ArrowRight, LoaderCircle, Mail, ShieldCheck } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { requestPasswordReset } from "@/lib/api";

export function ForgotPasswordClient() {
  const t = useTranslations("passwordRecovery");
  const locale = useLocale();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await requestPasswordReset(email);
      setSuccess(t("requestSuccess"));
    } catch {
      setError(t("requestError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="section-pad">
      <div className="page-shell mx-auto max-w-2xl">
        <div className="glass-panel rounded-3xl p-6 sm:p-10">
          <span className="eyebrow">
            <ShieldCheck className="h-3.5 w-3.5" />
            {t("eyebrow")}
          </span>
          <h1 className="section-title mt-7">{t("forgotTitle")}</h1>
          <p className="section-copy mt-5">{t("forgotDescription")}</p>
          <form className="mt-8" onSubmit={submit}>
            <label htmlFor="recovery-email" className="field-label">
              {t("email")}
            </label>
            <div className="relative">
              <Mail className="pointer-events-none absolute start-4 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
              <input
                id="recovery-email"
                type="email"
                className="field-control ps-11"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                required
              />
            </div>
            {success && (
              <StatusMessage tone="success" className="mt-5">
                {success}
              </StatusMessage>
            )}
            {error && (
              <StatusMessage tone="error" className="mt-5">
                {error}
              </StatusMessage>
            )}
            <Button
              type="submit"
              size="lg"
              className="mt-7 w-full"
              disabled={busy}
            >
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
              {busy ? t("sending") : t("send")}
              {!busy ? <ArrowRight className="h-4 w-4 rtl:rotate-180" /> : null}
            </Button>
          </form>
          <Link
            href={`/${locale}/login`}
            className="mt-6 block text-center text-sm font-semibold text-electric-200 hover:text-electric-100"
          >
            {t("backToLogin")}
          </Link>
        </div>
      </div>
    </section>
  );
}
