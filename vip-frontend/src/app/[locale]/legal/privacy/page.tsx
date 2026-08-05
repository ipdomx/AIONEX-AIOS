import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { LegalClient } from "@/components/pages/legal-client";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "legal" });
  return localizedMetadata({ locale, path: "legal/privacy", title: t("privacyTitle"), description: t("privacyIntro") });
}

export default async function LegalPage({ params }: PageProps) {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  setRequestLocale(locale);
  return <LegalClient kind="privacy" />;
}
