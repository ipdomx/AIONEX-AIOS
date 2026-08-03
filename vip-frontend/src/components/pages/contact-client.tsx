"use client";

import {
  LoaderCircle,
  LogIn,
  MessageSquareText,
  Send,
  ShieldCheck,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import { createSupportRequest } from "@/lib/api";

export function ContactClient() {
  const t = useTranslations("contact");
  const locale = useLocale();
  const { isAuthenticated, isLoading } = useAuth();
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isAuthenticated) return;
    setSubmitting(true);
    setResult(null);
    try {
      await createSupportRequest(subject.trim(), message.trim());
      setSubject("");
      setMessage("");
      setResult({ tone: "success", text: t("sent") });
    } catch {
      setResult({ tone: "error", text: t("sendError") });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="section-pad">
      <div className="page-shell grid gap-10 lg:grid-cols-[.8fr_1.2fr] lg:gap-16">
        <div>
          <span className="eyebrow">{t("eyebrow")}</span>
          <h1 className="section-title mt-7">{t("title")}</h1>
          <p className="section-copy mt-6">{t("description")}</p>
          <div className="mt-8 rounded-2xl border border-electric-300/15 bg-electric-400/[0.06] p-5">
            <div className="flex items-start gap-3">
              <ShieldCheck
                className="mt-0.5 h-5 w-5 shrink-0 text-electric-200"
                aria-hidden="true"
              />
              <div>
                <p className="text-sm font-semibold">{t("privateChannel")}</p>
                <p className="mt-2 text-sm leading-6 text-white/45">
                  {t("privacyNotice")}
                </p>
              </div>
            </div>
          </div>
        </div>

        <form
          onSubmit={submitRequest}
          className="glass-panel rounded-3xl p-6 sm:p-9"
        >
          <MessageSquareText
            className="h-7 w-7 text-electric-200"
            aria-hidden="true"
          />
          <h2 className="mt-5 text-xl font-semibold">{t("formTitle")}</h2>
          {!isLoading && !isAuthenticated && (
            <StatusMessage className="mt-6">
              <p>{t("signInRequired")}</p>
              <Link
                href={`/${locale}/login`}
                className="mt-2 inline-flex items-center gap-2 font-semibold text-electric-100 hover:text-white"
              >
                <LogIn className="h-4 w-4" aria-hidden="true" />
                {t("signIn")}
              </Link>
            </StatusMessage>
          )}
          <div className="mt-7">
            <label htmlFor="contact-subject" className="field-label">
              {t("subject")}
            </label>
            <input
              id="contact-subject"
              className="field-control"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              minLength={3}
              maxLength={120}
              required
              autoComplete="off"
              disabled={!isAuthenticated || submitting}
            />
          </div>
          <div className="mt-5">
            <label htmlFor="contact-message" className="field-label">
              {t("message")}
            </label>
            <textarea
              id="contact-message"
              className="field-control min-h-44 resize-y"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              minLength={10}
              maxLength={4000}
              required
              disabled={!isAuthenticated || submitting}
            />
          </div>
          {result && (
            <StatusMessage tone={result.tone} className="mt-5">
              {result.text}
            </StatusMessage>
          )}
          <Button
            type="submit"
            size="lg"
            className="mt-7 w-full sm:w-auto"
            disabled={!isAuthenticated || submitting || isLoading}
          >
            {submitting ? t("sending") : t("send")}
            {submitting ? (
              <LoaderCircle
                className="h-4 w-4 animate-spin"
                aria-hidden="true"
              />
            ) : (
              <Send className="h-4 w-4" aria-hidden="true" />
            )}
          </Button>
        </form>
      </div>
    </section>
  );
}
