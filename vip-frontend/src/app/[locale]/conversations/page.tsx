import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { ConversationsClient } from "@/components/pages/conversations-client";
import { isLocale, type Locale } from "@/i18n";
import { localizedMetadata } from "@/lib/metadata";

type PageProps = { params: Promise<{ locale: string }> };
export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { locale: value } = await params;
  const locale: Locale = isLocale(value) ? value : "en";
  const t = await getTranslations({ locale, namespace: "conversations" });
  return localizedMetadata({ locale, path: "conversations", title: t("title"), description: t("description"), noIndex: true });
}
export default function ConversationsPage() {
  return <ConversationsClient />;
}
