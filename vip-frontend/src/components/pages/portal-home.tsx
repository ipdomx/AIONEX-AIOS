/* eslint-disable @next/next/no-img-element */
"use client";

import {
  ArrowUpRight,
  BarChart3,
  BrainCircuit,
  CheckCircle2,
  HelpCircle,
  Image as ImageIcon,
  Network,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";
import type { LocalizedPortalText, PortalSection } from "@/types/portal";

const iconMap = {
  workflow: Workflow,
  brain: BrainCircuit,
  shield: ShieldCheck,
  network: Network,
  chart: BarChart3,
  help: HelpCircle,
  image: ImageIcon,
};

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function PortalHome() {
  const t = useTranslations("home");
  const { configuration } = usePortalExperience();
  const configured = configuration?.pages.home?.sections
    ?.filter((section) => section.enabled)
    .sort((a, b) => a.order - b.order);

  const fallbackSections: PortalSection[] = [
    {
      id: "hero",
      type: "hero",
      enabled: true,
      order: 10,
      content: {
        eyebrow: { ar: t("eyebrow"), en: t("eyebrow") },
        title_lead: { ar: t("titleLead"), en: t("titleLead") },
        title_accent: { ar: t("titleAccent"), en: t("titleAccent") },
        description: { ar: t("description"), en: t("description") },
        primary_label: { ar: t("start"), en: t("start") },
        primary_url: "/register",
        secondary_label: { ar: t("discover"), en: t("discover") },
        secondary_url: "/about",
        honesty_note: { ar: t("honestyNote"), en: t("honestyNote") },
        image_url: "/brand/aionex-mark.svg",
      },
    },
    {
      id: "capabilities",
      type: "features",
      enabled: true,
      order: 20,
      content: {
        eyebrow: { ar: t("capabilitiesEyebrow"), en: t("capabilitiesEyebrow") },
        title: { ar: t("capabilitiesTitle"), en: t("capabilitiesTitle") },
        description: { ar: t("capabilitiesCopy"), en: t("capabilitiesCopy") },
        items: [1, 2, 3, 4, 5].map((number) => ({
          icon: ["workflow", "brain", "shield", "network", "shield"][number - 1],
          title: { ar: t(`capability${number}Title`), en: t(`capability${number}Title`) },
          copy: { ar: t(`capability${number}Copy`), en: t(`capability${number}Copy`) },
        })),
      },
    },
    {
      id: "workflow",
      type: "steps",
      enabled: true,
      order: 30,
      content: {
        eyebrow: { ar: t("workflowEyebrow"), en: t("workflowEyebrow") },
        title: { ar: t("workflowTitle"), en: t("workflowTitle") },
        description: { ar: t("workflowCopy"), en: t("workflowCopy") },
        items: [1, 2, 3].map((number) => ({
          title: { ar: t(`workflow${number}Title`), en: t(`workflow${number}Title`) },
          copy: { ar: t(`workflow${number}Copy`), en: t(`workflow${number}Copy`) },
        })),
      },
    },
    {
      id: "cta",
      type: "cta",
      enabled: true,
      order: 40,
      content: {
        title: { ar: t("ctaTitle"), en: t("ctaTitle") },
        description: { ar: t("ctaCopy"), en: t("ctaCopy") },
        button_label: { ar: t("ctaButton"), en: t("ctaButton") },
        button_url: "/register",
      },
    },
  ];

  const sections = configured?.length ? configured : fallbackSections;
  return <PortalSectionList sections={sections} />;
}

export function PortalSectionList({ sections }: { sections: PortalSection[] }) {
  const { text, href } = usePortalExperience();
  return <>{sections.filter((section) => section.enabled).sort((a, b) => a.order - b.order).map((section) => <PortalSectionRenderer key={section.id} section={section} text={text} href={href} />)}</>;
}

export function PortalSectionRenderer({
  section,
  text,
  href,
}: {
  section: PortalSection;
  text: (value: LocalizedPortalText | undefined, fallback?: string) => string;
  href: (value: string) => string;
}) {
  const content = object(section.content);
  const localized = (key: string, fallback = "") => text(content[key] as LocalizedPortalText | undefined, fallback);
  if (section.type === "hero") {
    const imageUrl = String(content.image_url || "/brand/aionex-mark.svg");
    return (
      <section className="relative min-h-[calc(100vh-5rem)] overflow-hidden py-16 sm:py-20 lg:flex lg:items-center lg:py-24">
        <div className="pointer-events-none absolute inset-0 grid-surface opacity-70" />
        <div className="page-shell relative grid items-center gap-14 lg:grid-cols-[1.02fr_.98fr]">
          <div className="max-w-3xl">
            <div className="eyebrow reveal-up"><Sparkles className="h-3.5 w-3.5" />{localized("eyebrow")}</div>
            <h1 className="reveal-up reveal-delay-1 mt-7 text-balance text-4xl font-semibold leading-[1.08] tracking-[-0.045em] sm:text-6xl lg:text-7xl">
              {localized("title_lead")} <span className="title-gradient">{localized("title_accent")}</span>
            </h1>
            <p className="section-copy reveal-up reveal-delay-2 mt-7 max-w-2xl">{localized("description")}</p>
            <div className="reveal-up reveal-delay-3 mt-9 flex flex-col gap-3 sm:flex-row">
              <Link href={href(String(content.primary_url || "/register"))} className="portal-primary-button inline-flex h-[52px] items-center justify-center gap-2 px-6 text-sm font-semibold text-white">
                {localized("primary_label")}<ArrowUpRight className="h-4 w-4" />
              </Link>
              <Link href={href(String(content.secondary_url || "/about"))} className="inline-flex h-[52px] items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] px-6 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white">
                {localized("secondary_label")}
              </Link>
            </div>
            {localized("honesty_note") && <p className="mt-5 text-xs leading-6 text-white/35">{localized("honesty_note")}</p>}
          </div>
          <div className="orbital-visual mx-auto aspect-square w-full max-w-[560px] p-[11%]">
            <div className="glass-panel relative z-10 flex h-full flex-col items-center justify-center overflow-hidden rounded-[2rem] p-8 text-center shadow-glow">
              <img src={imageUrl} alt="" className="h-32 w-32 object-contain sm:h-40 sm:w-40" />
              <p className="mt-5 text-xs font-bold uppercase tracking-[0.26em] text-electric-200">AIONEX AIOS</p>
              <p className="mt-3 max-w-xs text-sm leading-6 text-white/50">{localized("visual_copy", localized("description"))}</p>
            </div>
          </div>
        </div>
      </section>
    );
  }
  if (section.type === "features") {
    return (
      <section className="section-pad border-y border-white/[0.07] bg-black/10">
        <div className="page-shell">
          <div className="max-w-3xl"><span className="eyebrow">{localized("eyebrow")}</span><h2 className="section-title mt-6">{localized("title")}</h2><p className="section-copy mt-5">{localized("description")}</p></div>
          <div className="mt-12 grid gap-4 md:grid-cols-2">
            {array(content.items).map((raw, index) => {
              const item = object(raw);
              const Icon = iconMap[String(item.icon || "workflow") as keyof typeof iconMap] || Workflow;
              return <article key={`${section.id}-${index}`} className="glass-panel rounded-2xl p-6 sm:p-8"><Icon className="h-6 w-6 text-electric-200" /><h3 className="mt-6 text-xl font-semibold">{text(item.title as LocalizedPortalText)}</h3><p className="mt-3 text-sm leading-7 text-white/50">{text(item.copy as LocalizedPortalText)}</p></article>;
            })}
          </div>
        </div>
      </section>
    );
  }
  if (section.type === "steps") {
    return (
      <section className="section-pad"><div className="page-shell grid gap-12 lg:grid-cols-[.8fr_1.2fr] lg:gap-20"><div><span className="eyebrow">{localized("eyebrow")}</span><h2 className="section-title mt-6">{localized("title")}</h2><p className="section-copy mt-5">{localized("description")}</p></div><ol className="space-y-4">{array(content.items).map((raw, index) => { const item = object(raw); return <li key={`${section.id}-${index}`} className="glass-panel grid gap-4 rounded-2xl p-6 sm:grid-cols-[auto_1fr]"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-electric-400/15 text-sm font-bold text-electric-100">{index + 1}</span><div><h3 className="font-semibold">{text(item.title as LocalizedPortalText)}</h3><p className="mt-2 text-sm leading-7 text-white/50">{text(item.copy as LocalizedPortalText)}</p></div></li>; })}</ol></div></section>
    );
  }
  if (section.type === "cta") {
    return <section className="pb-20 sm:pb-24 lg:pb-32"><div className="page-shell"><div className="relative overflow-hidden rounded-[2rem] border border-electric-300/15 bg-gradient-to-br from-electric-400/[0.09] via-white/[0.035] to-violet-500/[0.1] p-8 sm:p-12 lg:p-16"><div className="relative grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end"><div className="max-w-3xl"><CheckCircle2 className="h-8 w-8 text-electric-200" /><h2 className="section-title mt-6">{localized("title")}</h2><p className="section-copy mt-5">{localized("description")}</p></div><Link href={href(String(content.button_url || "/register"))} className="portal-primary-button inline-flex h-[52px] items-center justify-center gap-2 px-6 text-sm font-bold text-white">{localized("button_label")}<ArrowUpRight className="h-4 w-4" /></Link></div></div></div></section>;
  }
  if (section.type === "stats") {
    return <section className="section-pad"><div className="page-shell grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{array(content.items).map((raw, index) => { const item=object(raw); return <div key={index} className="glass-panel rounded-2xl p-6 text-center"><p className="text-3xl font-bold text-electric-200">{String(item.value || "")}</p><p className="mt-2 text-sm text-white/50">{text(item.label as LocalizedPortalText)}</p></div>; })}</div></section>;
  }
  if (section.type === "faq") {
    return <section className="section-pad"><div className="page-shell max-w-4xl"><h2 className="section-title">{localized("title")}</h2><div className="mt-8 space-y-3">{array(content.items).map((raw,index)=>{const item=object(raw);return <details key={index} className="glass-panel rounded-2xl p-5"><summary className="cursor-pointer font-semibold">{text(item.question as LocalizedPortalText)}</summary><p className="mt-4 text-sm leading-7 text-white/50">{text(item.answer as LocalizedPortalText)}</p></details>;})}</div></div></section>;
  }
  if (section.type === "image-text" || section.type === "rich-text") {
    const image = String(content.image_url || "");
    return <section className="section-pad"><div className={`page-shell grid gap-10 ${image ? "lg:grid-cols-2 lg:items-center" : "max-w-4xl"}`}><div><span className="eyebrow">{localized("eyebrow")}</span><h2 className="section-title mt-6">{localized("title")}</h2><p className="section-copy mt-5 whitespace-pre-line">{localized("body", localized("description"))}</p></div>{image && <img src={image} alt={localized("image_alt")} className="w-full rounded-[2rem] border border-white/10 object-cover" />}</div></section>;
  }
  if (section.type === "logo-cloud") {
    return <section className="section-pad"><div className="page-shell"><h2 className="text-center text-sm font-semibold text-white/45">{localized("title")}</h2><div className="mt-8 flex flex-wrap items-center justify-center gap-8">{array(content.items).map((raw,index)=>{const item=object(raw);return <img key={index} src={String(item.image_url || "")} alt={text(item.alt as LocalizedPortalText)} className="h-10 max-w-36 object-contain opacity-70" />;})}</div></div></section>;
  }
  return null;
}
