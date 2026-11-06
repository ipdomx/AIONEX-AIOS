import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { DataDeletionClient } from "@/components/pages/data-deletion-client";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

// Public page: Meta's "Data Deletion Instructions URL" and the status page
// behind the confirmation URL returned by the data-deletion callback.
export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "dataDeletion" });
  return localizedMetadata({ locale, path: "legal/data-deletion", title: t("title"), description: t("intro") });
}

export default async function DataDeletionPage({ params }: PageProps) {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  setRequestLocale(locale);
  return <DataDeletionClient />;
}
