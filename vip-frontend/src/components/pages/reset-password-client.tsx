"use client";

import { KeyRound, LoaderCircle, ShieldCheck } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { ApiError, confirmPasswordReset } from "@/lib/api";

export function ResetPasswordClient() {
  const t = useTranslations("passwordRecovery");
  const locale = useLocale();
  const search = useSearchParams();
  const token = search.get("token") || "";
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const password = String(form.get("password") || "");
    const confirmation = String(form.get("confirmation") || "");
    setError("");
    setSuccess("");
    if (!token) {
      setError(t("invalidToken"));
      return;
    }
    if (password !== confirmation) {
      setError(t("mismatch"));
      return;
    }
    setBusy(true);
    try {
      await confirmPasswordReset(token, password);
      formElement.reset();
      if (typeof window !== "undefined") {
        window.history.replaceState(null, "", window.location.pathname);
      }
      setSuccess(t("resetSuccess"));
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 400) {
        setError(t("invalidToken"));
      } else if (cause instanceof ApiError && cause.status === 409) {
        setError(t("samePassword"));
      } else {
        setError(t("resetError"));
      }
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
          <h1 className="section-title mt-7">{t("resetTitle")}</h1>
          <p className="section-copy mt-5">{t("resetDescription")}</p>
          <form className="mt-8 space-y-5" onSubmit={submit}>
            <div>
              <label htmlFor="reset-password" className="field-label">
                {t("newPassword")}
              </label>
              <input
                id="reset-password"
                name="password"
                type="password"
                className="field-control"
                minLength={12}
                maxLength={256}
                autoComplete="new-password"
                required
              />
            </div>
            <div>
              <label htmlFor="reset-confirmation" className="field-label">
                {t("confirmPassword")}
              </label>
              <input
                id="reset-confirmation"
                name="confirmation"
                type="password"
                className="field-control"
                minLength={12}
                maxLength={256}
                autoComplete="new-password"
                required
              />
            </div>
            {success && <StatusMessage tone="success">{success}</StatusMessage>}
            {error && <StatusMessage tone="error">{error}</StatusMessage>}
            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={busy || !token || Boolean(success)}
            >
              {busy ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <KeyRound className="h-4 w-4" />
              )}
              {busy ? t("resetting") : t("reset")}
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
