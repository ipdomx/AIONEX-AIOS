"use client";

import { useTranslations } from "next-intl";
import { PortalSectionList } from "@/components/pages/portal-home";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";

export function LegalClient({ kind }: { kind: "privacy" | "terms" }) {
  const t = useTranslations("legal");
  const { configuration } = usePortalExperience();
  const configured = configuration?.pages[kind]?.sections || [];
  if (configured.length) return <PortalSectionList sections={configured} />;
  return (
    <section className="section-pad">
      <article className="page-shell max-w-4xl">
        <span className="eyebrow">{t("effective")}</span>
        <h1 className="section-title mt-7">{t(`${kind}Title`)}</h1>
        <p className="section-copy mt-6">{t(`${kind}Intro`)}</p>
        {(kind === "terms" ? [1, 2, 3, 4, 5, 6] : [1, 2, 3, 4]).map((index) => (
          <section key={index} className="mt-10 border-t border-white/[0.07] pt-8">
            <h2 className="text-xl font-semibold">{t(`${kind}${index}Title`)}</h2>
            <p className="mt-4 whitespace-pre-line text-sm leading-8 text-white/55">{t(`${kind}${index}Copy`)}</p>
          </section>
        ))}
        {kind === "terms" && (
          <div className="mt-10 flex flex-col gap-3 border-t border-white/[0.07] pt-8 text-sm">
            <a className="text-violet-200 underline underline-offset-4" href="/legal/tencent-hunyuan-3d-2.1-license.txt" target="_blank" rel="noreferrer">
              {t("hunyuanLicense")}
            </a>
            <a className="text-violet-200 underline underline-offset-4" href="/legal/triposr-mit-license.txt" target="_blank" rel="noreferrer">
              {t("triposrLicense")}
            </a>
          </div>
        )}
      </article>
    </section>
  );
}
