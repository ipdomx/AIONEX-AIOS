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
        {[1, 2, 3, 4].map((index) => (
          <section key={index} className="mt-10 border-t border-white/[0.07] pt-8">
            <h2 className="text-xl font-semibold">{t(`${kind}${index}Title`)}</h2>
            <p className="mt-4 whitespace-pre-line text-sm leading-8 text-white/55">{t(`${kind}${index}Copy`)}</p>
          </section>
        ))}
      </article>
    </section>
  );
}
