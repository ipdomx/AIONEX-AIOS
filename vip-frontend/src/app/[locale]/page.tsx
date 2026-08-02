import type { Metadata } from "next";
import {
  ArrowUpRight,
  BrainCircuit,
  CheckCircle2,
  Network,
  ShieldCheck,
  Sparkles,
  Workflow
} from "lucide-react";
import { getTranslations, setRequestLocale } from "next-intl/server";
import Image from "next/image";
import Link from "next/link";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "meta" });
  return localizedMetadata({
    locale,
    title: t("homeTitle"),
    description: t("homeDescription")
  });
}

export default async function HomePage({ params }: PageProps) {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "home" });

  const capabilities = [
    { icon: Workflow, title: t("capability1Title"), copy: t("capability1Copy") },
    { icon: BrainCircuit, title: t("capability2Title"), copy: t("capability2Copy") },
    { icon: ShieldCheck, title: t("capability3Title"), copy: t("capability3Copy") },
    { icon: Network, title: t("capability4Title"), copy: t("capability4Copy") }
  ];
  const stages = [
    t("stage1"),
    t("stage2"),
    t("stage3"),
    t("stage4")
  ];
  const workflowSteps = [
    [t("workflow1Title"), t("workflow1Copy")],
    [t("workflow2Title"), t("workflow2Copy")],
    [t("workflow3Title"), t("workflow3Copy")]
  ];

  return (
    <>
      <section className="relative min-h-[calc(100vh-5rem)] overflow-hidden py-16 sm:py-20 lg:flex lg:items-center lg:py-24">
        <div className="pointer-events-none absolute inset-0 grid-surface opacity-70" />
        <div className="page-shell relative grid items-center gap-14 lg:grid-cols-[1.02fr_.98fr]">
          <div className="max-w-3xl">
            <div className="eyebrow reveal-up">
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              {t("eyebrow")}
            </div>
            <h1 className="reveal-up reveal-delay-1 mt-7 text-balance text-4xl font-semibold leading-[1.08] tracking-[-0.045em] sm:text-6xl lg:text-7xl">
              {t("titleLead")} <span className="title-gradient">{t("titleAccent")}</span>
            </h1>
            <p className="section-copy reveal-up reveal-delay-2 mt-7 max-w-2xl">
              {t("description")}
            </p>
            <div className="reveal-up reveal-delay-3 mt-9 flex flex-col gap-3 sm:flex-row">
              <Link href={`/${locale}/register`} className="inline-flex h-[52px] items-center justify-center gap-2 rounded-xl border border-electric-300/30 bg-gradient-to-r from-electric-500 to-violet-500 px-6 text-sm font-semibold text-white shadow-lg shadow-electric-500/20 transition hover:brightness-110">
                {t("start")}
                <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </Link>
              <Link href={`/${locale}/about`} className="inline-flex h-[52px] items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] px-6 text-sm font-semibold text-white/75 transition hover:bg-white/[0.08] hover:text-white">
                {t("discover")}
              </Link>
            </div>
            <p className="mt-5 text-xs leading-6 text-white/35">{t("honestyNote")}</p>
          </div>

          <div className="orbital-visual mx-auto aspect-square w-full max-w-[560px] p-[11%]" aria-label={t("visualLabel")}>
            <div className="absolute start-[8%] top-[23%] h-2.5 w-2.5 rounded-full bg-electric-300 text-electric-300 signal-dot" />
            <div className="absolute end-[11%] top-[54%] h-2.5 w-2.5 rounded-full bg-violet-400 text-violet-400 signal-dot [animation-delay:1.2s]" />
            <div className="glass-panel relative z-10 flex h-full flex-col items-center justify-center overflow-hidden rounded-[2rem] p-6 text-center shadow-glow sm:p-10">
              <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-electric-300/80 to-transparent" />
              <Image src="/brand/aionex-mark.svg" alt="" width={164} height={164} className="h-28 w-28 sm:h-40 sm:w-40" priority />
              <p className="mt-5 text-xs font-bold uppercase tracking-[0.26em] text-electric-200">AIONEX AIOS</p>
              <p className="mt-3 max-w-xs text-sm leading-6 text-white/50">{t("visualCopy")}</p>
              <div className="mt-7 grid w-full grid-cols-2 gap-2">
                {stages.map((stage, index) => (
                  <div key={stage} className="flex items-center gap-2 rounded-xl border border-white/[0.07] bg-black/20 px-3 py-2.5 text-start text-[11px] text-white/55">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-electric-400/10 text-[9px] font-bold text-electric-200">{index + 1}</span>
                    {stage}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="section-pad border-y border-white/[0.07] bg-black/10">
        <div className="page-shell">
          <div className="max-w-3xl">
            <span className="eyebrow">{t("capabilitiesEyebrow")}</span>
            <h2 className="section-title mt-6">{t("capabilitiesTitle")}</h2>
            <p className="section-copy mt-5">{t("capabilitiesCopy")}</p>
          </div>
          <div className="mt-12 grid gap-4 md:grid-cols-2">
            {capabilities.map(({ icon: Icon, title, copy }, index) => (
              <article key={title} className="glass-panel group rounded-2xl p-6 transition duration-300 hover:-translate-y-1 hover:border-electric-300/20 sm:p-8">
                <div className="flex items-start justify-between gap-6">
                  <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-electric-300/20 bg-electric-400/[0.08] text-electric-200">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <span className="text-xs font-semibold text-white/20">0{index + 1}</span>
                </div>
                <h3 className="mt-7 text-xl font-semibold">{title}</h3>
                <p className="mt-3 text-sm leading-7 text-white/50">{copy}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section-pad">
        <div className="page-shell grid gap-12 lg:grid-cols-[.8fr_1.2fr] lg:gap-20">
          <div>
            <span className="eyebrow">{t("workflowEyebrow")}</span>
            <h2 className="section-title mt-6">{t("workflowTitle")}</h2>
            <p className="section-copy mt-5">{t("workflowCopy")}</p>
          </div>
          <ol className="space-y-4">
            {workflowSteps.map(([title, copy], index) => (
              <li key={title} className="glass-panel grid gap-4 rounded-2xl p-6 sm:grid-cols-[auto_1fr] sm:items-start">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-electric-400/20 to-violet-500/20 text-sm font-bold text-electric-100">{index + 1}</span>
                <div>
                  <h3 className="font-semibold">{title}</h3>
                  <p className="mt-2 text-sm leading-7 text-white/50">{copy}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="pb-20 sm:pb-24 lg:pb-32">
        <div className="page-shell">
          <div className="relative overflow-hidden rounded-[2rem] border border-electric-300/15 bg-gradient-to-br from-electric-400/[0.09] via-white/[0.035] to-violet-500/[0.1] p-8 sm:p-12 lg:p-16">
            <div className="pointer-events-none absolute -end-20 -top-20 h-64 w-64 rounded-full bg-electric-400/10 blur-3xl" />
            <div className="relative grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
              <div className="max-w-3xl">
                <CheckCircle2 className="h-8 w-8 text-electric-200" aria-hidden="true" />
                <h2 className="section-title mt-6">{t("ctaTitle")}</h2>
                <p className="section-copy mt-5">{t("ctaCopy")}</p>
              </div>
              <Link href={`/${locale}/register`} className="inline-flex h-[52px] items-center justify-center gap-2 rounded-xl bg-white px-6 text-sm font-bold text-ink-950 transition hover:bg-electric-50">
                {t("ctaButton")}
                <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
