"use client";

import {
  ExternalLink,
  LoaderCircle,
  LogIn,
  Mail,
  MapPin,
  MessageCircle,
  MessageSquareText,
  Phone,
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
import { usePortalExperience } from "@/components/portal/portal-experience-provider";

export function ContactClient() {
  const t = useTranslations("contact");
  const locale = useLocale();
  const { isAuthenticated, isLoading } = useAuth();
  const { configuration, text } = usePortalExperience();
  const contact = configuration?.contact ?? {
    support_email: "",
    sales_email: "",
    phone: "",
    whatsapp_url: "",
    address: { ar: "", en: "", fr: "", de: "", es: "", tr: "" },
    social_links: {},
  };
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
          {(contact.support_email || contact.sales_email || contact.phone || contact.whatsapp_url || text(contact.address) || Object.keys(contact.social_links).length > 0) && (
            <div className="mt-8 space-y-3 rounded-2xl border border-white/[0.07] bg-white/[0.025] p-5 text-sm text-white/55">
              {contact.support_email && <a className="flex items-center gap-3 hover:text-white" href={`mailto:${contact.support_email}`}><Mail className="h-4 w-4 text-electric-200" />{contact.support_email}</a>}
              {contact.sales_email && contact.sales_email !== contact.support_email && <a className="flex items-center gap-3 hover:text-white" href={`mailto:${contact.sales_email}`}><Mail className="h-4 w-4 text-violet-400" />{contact.sales_email}</a>}
              {contact.phone && <a className="flex items-center gap-3 hover:text-white" href={`tel:${contact.phone.replace(/[^+0-9]/g, "")}`}><Phone className="h-4 w-4 text-electric-200" />{contact.phone}</a>}
              {contact.whatsapp_url && <a className="flex items-center gap-3 hover:text-white" href={contact.whatsapp_url} target="_blank" rel="noreferrer"><MessageCircle className="h-4 w-4 text-emerald-300" />WhatsApp <ExternalLink className="h-3.5 w-3.5" /></a>}
              {text(contact.address) && <p className="flex items-start gap-3"><MapPin className="mt-0.5 h-4 w-4 shrink-0 text-electric-200" />{text(contact.address)}</p>}
              {Object.entries(contact.social_links || {}).map(([network, url]) => <a key={network} className="flex items-center gap-3 capitalize hover:text-white" href={url} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4 text-electric-200" />{network}</a>)}
            </div>
          )}

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
