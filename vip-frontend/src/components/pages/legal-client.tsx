"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { PortalSectionList } from "@/components/pages/portal-home";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";

// Facebook/Instagram (Meta) data use and deletion. Always shown on the privacy
// notice, also when the Owner configured custom sections, because Meta App
// Review requires the privacy policy to describe it.
function MetaDataSections() {
  const t = useTranslations("legal");
  const locale = useLocale();
  return (
    <>
      {[5, 6].map((index) => (
        <section key={index} className="mt-10 border-t border-white/[0.07] pt-8">
          <h2 className="text-xl font-semibold">{t(`privacy${index}Title`)}</h2>
          <p className="mt-4 whitespace-pre-line text-sm leading-8 text-white/55">{t(`privacy${index}Copy`)}</p>
        </section>
      ))}
      <div className="mt-6 text-sm">
        <Link className="text-crimson-200 underline underline-offset-4" href={`/${locale}/legal/data-deletion`}>
          {t("dataDeletionLink")}
        </Link>
      </div>
    </>
  );
}

export function LegalClient({ kind }: { kind: "privacy" | "terms" }) {
  const t = useTranslations("legal");
  const { configuration } = usePortalExperience();
  const configured = configuration?.pages[kind]?.sections || [];
  if (configured.length) {
    if (kind !== "privacy") return <PortalSectionList sections={configured} />;
    return (
      <>
        <PortalSectionList sections={configured} />
        <section className="section-pad pt-0">
          <article className="page-shell max-w-4xl">
            <MetaDataSections />
          </article>
        </section>
      </>
    );
  }
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
        {kind === "privacy" && <MetaDataSections />}
        {kind === "terms" && (
          <div className="mt-10 flex flex-col gap-3 border-t border-white/[0.07] pt-8 text-sm">
            <a className="text-crimson-200 underline underline-offset-4" href="/legal/tencent-hunyuan-3d-2.1-license.txt" target="_blank" rel="noreferrer">
              {t("hunyuanLicense")}
            </a>
            <a className="text-crimson-200 underline underline-offset-4" href="/legal/triposr-mit-license.txt" target="_blank" rel="noreferrer">
              {t("triposrLicense")}
            </a>
          </div>
        )}
      </article>
    </section>
  );
}
