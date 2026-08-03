import type { Metadata } from "next";
import { locales, type Locale } from "@/i18n";
import { SITE_URL } from "@/lib/site";

interface LocalizedMetadataInput {
  locale: Locale;
  path?: string;
  title: string;
  description: string;
  noIndex?: boolean;
}

export function localizedMetadata({
  locale,
  path = "",
  title,
  description,
  noIndex = false
}: LocalizedMetadataInput): Metadata {
  const normalizedPath = path.replace(/^\/+|\/+$/g, "");
  const suffix = normalizedPath ? `/${normalizedPath}` : "";
  const url = `${SITE_URL}/${locale}${suffix}`;

  return {
    title,
    description,
    alternates: {
      canonical: url,
      languages: Object.fromEntries(
        locales.map((item) => [item, `${SITE_URL}/${item}${suffix}`])
      )
    },
    robots: noIndex ? { index: false, follow: false } : undefined,
    openGraph: {
      type: "website",
      url,
      siteName: "AIONEX AIOS",
      title,
      description,
      locale
    },
    twitter: {
      card: "summary",
      title,
      description
    }
  };
}
