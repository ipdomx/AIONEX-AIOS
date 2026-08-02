import { getRequestConfig } from "next-intl/server";
import { notFound } from "next/navigation";

export const locales = ["ar", "en", "fr", "de", "es", "tr"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "en";

export function isLocale(value: string): value is Locale {
  return locales.includes(value as Locale);
}

export function localeDirection(locale: string): "rtl" | "ltr" {
  return locale === "ar" ? "rtl" : "ltr";
}

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  if (!requested || !isLocale(requested)) notFound();

  return {
    locale: requested,
    messages: (await import(`./messages/${requested}.json`)).default
  };
});
