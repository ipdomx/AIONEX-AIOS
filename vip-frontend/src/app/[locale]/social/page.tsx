import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { SocialClient } from "@/components/pages/social-client";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

// Static export: locale params come from generateStaticParams in
// src/app/[locale]/layout.tsx, like every other localized page.
export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "meta" });
  return localizedMetadata({ locale, path: "social", title: t("socialTitle"), description: t("socialDescription"), noIndex: true });
}

export default function SocialPage() {
  return <SocialClient />;
}
