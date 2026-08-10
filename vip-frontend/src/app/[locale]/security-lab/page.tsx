import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { SecurityLabClient } from "@/components/pages/security-lab-client";
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
    path: "security-lab",
    title: t("securityLabTitle"),
    description: t("securityLabDescription"),
    noIndex: true,
  });
}

export default function SecurityLabPage() {
  return <SecurityLabClient />;
}
