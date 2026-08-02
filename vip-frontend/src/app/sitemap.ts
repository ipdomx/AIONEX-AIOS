import type { MetadataRoute } from "next";
import { locales } from "@/i18n";
import { SITE_URL } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  const routes = ["", "/about", "/contact", "/legal/privacy", "/legal/terms"];
  return locales.flatMap((locale) =>
    routes.map((route) => ({
      url: `${SITE_URL}/${locale}${route}`,
      lastModified: new Date(),
      changeFrequency: route ? ("monthly" as const) : ("weekly" as const),
      priority: route ? 0.7 : 1
    }))
  );
}
