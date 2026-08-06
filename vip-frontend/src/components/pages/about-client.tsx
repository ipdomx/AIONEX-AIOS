"use client";

import {
  Blocks,
  Eye,
  Scale,
  ShieldCheck,
  Target,
  Workflow,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { PortalSectionList } from "@/components/pages/portal-home";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";

export function AboutClient() {
  const t = useTranslations("about");
  const { configuration } = usePortalExperience();
  const configured = configuration?.pages.about?.sections || [];
  if (configured.length) {
    return (
      <>
        <header className="section-pad border-b border-white/[0.07]">
          <div className="page-shell max-w-5xl text-center">
            <span className="eyebrow">{t("eyebrow")}</span>
            <h1 className="section-title mx-auto mt-7 max-w-4xl text-4xl sm:text-6xl">
              {t("title")}
            </h1>
            <p className="section-copy mx-auto mt-6 max-w-3xl">
              {t("description")}
            </p>
          </div>
        </header>
        <PortalSectionList sections={configured} />
      </>
    );
  }

  const principles = [
    {
      icon: ShieldCheck,
      title: t("principle1Title"),
      copy: t("principle1Copy"),
    },
    { icon: Scale, title: t("principle2Title"), copy: t("principle2Copy") },
    { icon: Workflow, title: t("principle3Title"), copy: t("principle3Copy") },
    { icon: Blocks, title: t("principle4Title"), copy: t("principle4Copy") },
  ];
  return (
    <>
      <section className="section-pad relative overflow-hidden border-b border-white/[0.07]">
        <div className="pointer-events-none absolute inset-0 grid-surface opacity-50" />
        <div className="page-shell relative max-w-5xl text-center">
          <span className="eyebrow">{t("eyebrow")}</span>
          <h1 className="section-title mx-auto mt-7 max-w-4xl text-4xl sm:text-6xl">
            {t("title")}
          </h1>
          <p className="section-copy mx-auto mt-6 max-w-3xl">
            {t("description")}
          </p>
        </div>
      </section>
      <section className="section-pad">
        <div className="page-shell grid gap-6 lg:grid-cols-2">
          <article className="glass-panel rounded-3xl p-8 sm:p-10">
            <Target className="h-8 w-8 text-electric-200" />
            <h2 className="mt-6 text-2xl font-semibold">{t("missionTitle")}</h2>
            <p className="mt-4 text-base leading-8 text-white/55">
              {t("missionCopy")}
            </p>
          </article>
          <article className="glass-panel rounded-3xl p-8 sm:p-10">
            <Eye className="h-8 w-8 text-violet-400" />
            <h2 className="mt-6 text-2xl font-semibold">{t("visionTitle")}</h2>
            <p className="mt-4 text-base leading-8 text-white/55">
              {t("visionCopy")}
            </p>
          </article>
        </div>
      </section>
      <section className="section-pad border-y border-white/[0.07] bg-black/10">
        <div className="page-shell">
          <div className="max-w-3xl">
            <span className="eyebrow">{t("principlesEyebrow")}</span>
            <h2 className="section-title mt-6">{t("principlesTitle")}</h2>
          </div>
          <div className="mt-12 grid gap-4 sm:grid-cols-2">
            {principles.map(({ icon: Icon, title, copy }) => (
              <article
                key={title}
                className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-6 sm:p-8"
              >
                <Icon className="h-6 w-6 text-electric-200" />
                <h3 className="mt-5 text-lg font-semibold">{title}</h3>
                <p className="mt-3 text-sm leading-7 text-white/50">{copy}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
      <section className="section-pad">
        <div className="page-shell max-w-4xl text-center">
          <h2 className="section-title">{t("scopeTitle")}</h2>
          <p className="section-copy mt-6">{t("scopeCopy")}</p>
        </div>
      </section>
    </>
  );
}
