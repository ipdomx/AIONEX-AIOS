import type { Metadata, Viewport } from "next";
import {
  getMessages,
  getTranslations,
  setRequestLocale,
} from "next-intl/server";
import { notFound } from "next/navigation";
import { Footer } from "@/components/layout/footer";
import { SiteFrame } from "@/components/layout/site-frame";
import { AuthProvider } from "@/hooks/use-auth";
import { PwaRegister } from "@/components/pwa/pwa-register";
import { PortalExperienceProvider } from "@/components/portal/portal-experience-provider";
import { localeDirection, locales, type Locale } from "@/i18n";
import { SITE_URL } from "@/lib/site";
import "@/styles/globals.css";

type Props = {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#03050a",
  colorScheme: "dark light",
};

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: Omit<Props, "children">): Promise<Metadata> {
  const { locale } = await params;
  if (!locales.includes(locale as Locale)) notFound();
  const t = await getTranslations({ locale, namespace: "meta" });
  return {
    metadataBase: new URL(SITE_URL),
    applicationName: "AIONEX AIOS",
    title: t("title"),
    description: t("description"),
    keywords: [
      "AIONEX",
      "AIOS",
      "enterprise AI",
      "AI agents",
      "project automation",
    ],
    authors: [{ name: "AIONEX AIOS" }],
    creator: "AIONEX AIOS",
    publisher: "AIONEX AIOS",
    icons: {
      icon: "/brand/aionex-mark.svg",
      shortcut: "/brand/aionex-mark.svg",
      apple: "/icons/aionex-180.png",
    },
    manifest: "/manifest.webmanifest",
    appleWebApp: { capable: true, title: "AIONEX", statusBarStyle: "black-translucent" },
    alternates: {
      canonical: `${SITE_URL}/${locale}`,
      languages: Object.fromEntries(
        locales.map((item) => [item, `${SITE_URL}/${item}`]),
      ),
    },
    openGraph: {
      type: "website",
      url: `${SITE_URL}/${locale}`,
      siteName: "AIONEX AIOS",
      title: t("title"),
      description: t("description"),
      locale,
    },
    twitter: {
      card: "summary",
      title: t("title"),
      description: t("description"),
    },
  };
}

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params;
  if (!locales.includes(locale as Locale)) notFound();
  setRequestLocale(locale);
  const messages = await getMessages();
  const direction = localeDirection(locale);
  const websiteSchema = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "AIONEX AIOS",
    url: SITE_URL,
    inLanguage: locales,
  };
  return (
    <html lang={locale} dir={direction} suppressHydrationWarning>
      <body className={locale === "ar" ? "font-arabic" : "font-sans"}>
        <PortalExperienceProvider
          messages={messages}
          locale={locale as Locale}
        >
          <AuthProvider>
            <PwaRegister />
            <script
              type="application/ld+json"
              dangerouslySetInnerHTML={{
                __html: JSON.stringify(websiteSchema),
              }}
            />
            <SiteFrame footer={<Footer />}>{children}</SiteFrame>
          </AuthProvider>
        </PortalExperienceProvider>
      </body>
    </html>
  );
}
