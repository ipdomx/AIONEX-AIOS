import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "legal" });
  return localizedMetadata({ locale, path: "legal/privacy", title: t("privacyTitle"), description: t("privacyIntro") });
}

export default async function PrivacyPage({ params }: PageProps) {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "legal" });
  return (
    <section className="section-pad">
      <article className="page-shell max-w-4xl">
        <span className="eyebrow">{t("effective")}</span>
        <h1 className="section-title mt-7">{t("privacyTitle")}</h1>
        <p className="section-copy mt-6">{t("privacyIntro")}</p>
        {[1, 2, 3, 4].map((index) => (
          <section key={index} className="mt-10 border-t border-white/[0.07] pt-8">
            <h2 className="text-xl font-semibold">{t(`privacy${index}Title`)}</h2>
            <p className="mt-4 text-sm leading-8 text-white/55">{t(`privacy${index}Copy`)}</p>
          </section>
        ))}
      </article>
    </section>
  );
}
