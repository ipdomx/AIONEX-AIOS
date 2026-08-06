import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { BillingClient } from "@/components/pages/billing-client";
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
    path: "billing",
    title: t("billingTitle"),
    description: t("billingDescription"),
    noIndex: true,
  });
}

export default function BillingPage() {
  return (
    <Suspense fallback={null}>
      <BillingClient />
    </Suspense>
  );
}
