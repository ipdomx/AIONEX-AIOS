"use client";

import { ExternalLink, Github, MessageSquareText } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { GITHUB_ISSUE_URL, GITHUB_URL } from "@/lib/site";

export function ContactClient() {
  const t = useTranslations("contact");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");

  function openIssue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const url = new URL(GITHUB_ISSUE_URL);
    url.searchParams.set("title", subject.trim());
    url.searchParams.set("body", message.trim());
    window.open(url.toString(), "_blank", "noopener,noreferrer");
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
              <Github className="mt-0.5 h-5 w-5 shrink-0 text-electric-200" aria-hidden="true" />
              <div>
                <p className="text-sm font-semibold">{t("officialChannel")}</p>
                <p className="mt-2 text-sm leading-6 text-white/45">{t("publicNotice")}</p>
              </div>
            </div>
          </div>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-electric-200 hover:text-electric-100">
            {t("viewRepository")}
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
          </a>
        </div>

        <form onSubmit={openIssue} className="glass-panel rounded-3xl p-6 sm:p-9">
          <MessageSquareText className="h-7 w-7 text-electric-200" aria-hidden="true" />
          <h2 className="mt-5 text-xl font-semibold">{t("formTitle")}</h2>
          <div className="mt-7">
            <label htmlFor="contact-subject" className="field-label">{t("subject")}</label>
            <input id="contact-subject" className="field-control" value={subject} onChange={(event) => setSubject(event.target.value)} minLength={3} maxLength={120} required autoComplete="off" />
          </div>
          <div className="mt-5">
            <label htmlFor="contact-message" className="field-label">{t("message")}</label>
            <textarea id="contact-message" className="field-control min-h-44 resize-y" value={message} onChange={(event) => setMessage(event.target.value)} minLength={10} maxLength={4000} required />
          </div>
          <p className="mt-4 text-xs leading-6 text-white/35">{t("githubAccount")}</p>
          <Button type="submit" size="lg" className="mt-7 w-full sm:w-auto">
            {t("openIssue")}
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
          </Button>
        </form>
      </div>
    </section>
  );
}
