import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { PricingClient } from "@/components/pages/pricing-client";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "meta" });
  return localizedMetadata({
    locale,
    path: "pricing",
    title: t.has("pricingTitle") ? t("pricingTitle") : "AIONEX AIOS Pricing",
    description: t.has("pricingDescription") ? t("pricingDescription") : "AIONEX AIOS plans and subscription periods.",
  });
}

export default async function PricingPage({ params }: PageProps) {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  setRequestLocale(locale);
  return <PricingClient />;
}
