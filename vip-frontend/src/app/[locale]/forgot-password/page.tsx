import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { ForgotPasswordClient } from "@/components/pages/forgot-password-client";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "passwordRecovery" });
  return localizedMetadata({
    locale,
    path: "forgot-password",
    title: t("forgotTitle"),
    description: t("forgotDescription"),
    noIndex: true,
  });
}

export default function ForgotPasswordPage() {
  return <ForgotPasswordClient />;
}
