import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { PortalHome } from "@/components/pages/portal-home";
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
  return <PortalHome />;
}
