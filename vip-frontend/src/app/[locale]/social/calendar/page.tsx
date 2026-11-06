import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { SocialCalendarClient } from "@/components/pages/social-calendar-client";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

// Static export: locale params come from generateStaticParams in
// src/app/[locale]/layout.tsx, like every other localized page.
export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "meta" });
  return localizedMetadata({
    locale,
    path: "social/calendar",
    title: t("socialCalendarTitle"),
    description: t("socialCalendarDescription"),
    noIndex: true,
  });
}

export default function SocialCalendarPage() {
  return <SocialCalendarClient />;
}
