import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { CampaignsClient } from "@/components/pages/campaigns-client";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "meta" });
  return localizedMetadata({
    locale,
    path: "campaigns",
    title: t("campaignsTitle"),
    description: t("campaignsDescription"),
    noIndex: true,
  });
}

export default function CampaignsPage() {
  return <CampaignsClient />;
}
