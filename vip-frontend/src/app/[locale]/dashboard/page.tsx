import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { DashboardClient } from "@/components/pages/dashboard-client";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "meta" });
  return localizedMetadata({
    locale,
    path: "dashboard",
    title: t("dashboardTitle"),
    description: t("dashboardDescription"),
    noIndex: true,
  });
}

export default async function DashboardPage({ params }: PageProps) {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  setRequestLocale(locale);
  return <DashboardClient />;
}
