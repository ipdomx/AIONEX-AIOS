import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { LoginClient } from "@/components/pages/login-client";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "meta" });
  return localizedMetadata({ locale, path: "login", title: t("loginTitle"), description: t("loginDescription"), noIndex: true });
}

export default function LoginPage() {
  return <LoginClient />;
}
