"use client";

import {
  NextIntlClientProvider,
  type AbstractIntlMessages,
} from "next-intl";
import { usePathname } from "next/navigation";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type {
  LocalizedPortalText,
  PortalConfiguration,
  PortalLocale,
  PublishedPortalConfiguration,
} from "@/types/portal";

const API_ROOT = (process.env.NEXT_PUBLIC_API_URL || "/api/v1").replace(/\/$/, "");

const PortalContext = createContext<{
  configuration: PortalConfiguration | null;
  publicationVersion: number | null;
  locale: PortalLocale;
  text: (value: LocalizedPortalText | undefined, fallback?: string) => string;
  href: (value: string) => string;
}>({
  configuration: null,
  publicationVersion: null,
  locale: "en",
  text: (_value, fallback = "") => fallback,
  href: (value) => value,
});

function mergeTranslationOverride(
  messages: AbstractIntlMessages,
  path: string,
  value: string,
): void {
  const parts = path.split(".").filter(Boolean);
  if (!parts.length) return;
  let target = messages as Record<string, unknown>;
  for (const part of parts.slice(0, -1)) {
    const current = target[part];
    if (!current || typeof current !== "object" || Array.isArray(current)) {
      target[part] = {};
    }
    target = target[part] as Record<string, unknown>;
  }
  target[parts.at(-1)!] = value;
}

function resolvePortalHref(value: string, locale: PortalLocale): string {
  if (!value) return `/${locale}`;
  if (/^https:\/\//i.test(value)) return value;
  if (!value.startsWith("/")) return value;
  if (value.startsWith("/api/") || /^\/(ar|en|fr|de|es|tr)(\/|$)/.test(value)) {
    return value;
  }
  return value === "/" ? `/${locale}` : `/${locale}${value}`;
}

function applyTheme(configuration: PortalConfiguration | null, locale: PortalLocale) {
  if (!configuration) return () => undefined;
  const root = document.documentElement;
  const theme = configuration.theme;
  const variables: Record<string, string> = {
    "--page": theme.page_color,
    "--page-deep": theme.page_deep_color,
    "--surface": theme.surface_color,
    "--text": theme.text_color,
    "--muted-solid": theme.muted_color,
    "--primary": theme.primary_color,
    "--secondary": theme.secondary_color,
    "--success": theme.success_color,
    "--warning": theme.warning_color,
    "--danger": theme.danger_color,
    "--portal-radius": `${theme.radius_px}px`,
    "--portal-max-width": `${theme.page_max_width_px}px`,
    "--portal-section-space": `${theme.section_spacing_px}px`,
    "--portal-logo-size": `${theme.logo_size_px}px`,
    "--portal-heading-font": theme.heading_font_family,
    "--portal-body-font": theme.body_font_family,
    "--portal-arabic-font": theme.arabic_font_family,
    "--portal-background-image": theme.background_image_url
      ? `url("${theme.background_image_url}")`
      : "none",
    "--portal-background-position": theme.background_image_position,
    "--portal-background-opacity": String(theme.background_image_opacity),
  };
  for (const [key, value] of Object.entries(variables)) {
    root.style.setProperty(key, value);
  }
  root.dataset.portalButtonStyle = theme.button_style;
  root.dataset.portalGrid = theme.background_grid ? "on" : "off";
  root.dataset.portalGlow = theme.background_glow ? "on" : "off";
  const fontStyle = document.createElement("style");
  fontStyle.dataset.portalFonts = "true";
  const fontRules = [
    theme.heading_font_url
      ? `@font-face{font-family:"AIONEX Owner Heading";src:url("${theme.heading_font_url}") format("woff2");font-display:swap}`
      : "",
    theme.body_font_url
      ? `@font-face{font-family:"AIONEX Owner Body";src:url("${theme.body_font_url}") format("woff2");font-display:swap}`
      : "",
    theme.arabic_font_url
      ? `@font-face{font-family:"AIONEX Owner Arabic";src:url("${theme.arabic_font_url}") format("woff2");font-display:swap}`
      : "",
  ].join("\n");
  fontStyle.textContent = fontRules;
  document.head.appendChild(fontStyle);
  const storedTheme = window.localStorage.getItem("aionex.theme");
  if (!storedTheme && theme.default_mode !== "system") {
    root.classList.toggle("light", theme.default_mode === "light");
  }
  root.lang = locale;
  return () => {
    fontStyle.remove();
  };
}

export function PortalExperienceProvider({
  children,
  locale,
  messages,
}: {
  children: React.ReactNode;
  locale: PortalLocale;
  messages: AbstractIntlMessages;
}) {
  const [published, setPublished] = useState<PublishedPortalConfiguration | null>(null);
  const pathname = usePathname();

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_ROOT}/portal/published`, {
      headers: { Accept: "application/json" },
      credentials: "omit",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Portal configuration ${response.status}`);
        return (await response.json()) as PublishedPortalConfiguration;
      })
      .then(setPublished)
      .catch((error) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setPublished(null);
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(
    () => applyTheme(published?.configuration || null, locale),
    [published, locale],
  );

  useEffect(() => {
    const configuration = published?.configuration;
    if (!configuration) return;
    const relative = pathname.replace(new RegExp(`^/${locale}/?`), "").replace(/\/$/, "");
    const page = Object.values(configuration.pages).find((item) => item.slug === relative);
    if (page) {
      const title = page.seo.title[locale] || page.seo.title.en || page.seo.title.ar;
      const description = page.seo.description[locale] || page.seo.description.en || page.seo.description.ar;
      if (title) document.title = title;
      let meta = document.querySelector('meta[name="description"]') as HTMLMetaElement | null;
      if (!meta) {
        meta = document.createElement("meta");
        meta.name = "description";
        document.head.appendChild(meta);
      }
      meta.content = description || "";
      if (page.seo.noindex) {
        let robots = document.querySelector('meta[name="robots"]') as HTMLMetaElement | null;
        if (!robots) {
          robots = document.createElement("meta");
          robots.name = "robots";
          document.head.appendChild(robots);
        }
        robots.content = "noindex,nofollow";
      }
    }
    const favicon = configuration.branding.favicon_url;
    if (favicon) {
      let link = document.querySelector('link[rel="icon"]') as HTMLLinkElement | null;
      if (!link) {
        link = document.createElement("link");
        link.rel = "icon";
        document.head.appendChild(link);
      }
      link.href = favicon;
    }
  }, [locale, pathname, published]);


  const mergedMessages = useMemo(() => {
    const next = structuredClone(messages) as AbstractIntlMessages;
    const overrides = published?.configuration.translation_overrides || {};
    for (const [path, localized] of Object.entries(overrides)) {
      const value = localized[locale] || localized.en || localized.ar || "";
      if (value) mergeTranslationOverride(next, path, value);
    }
    return next;
  }, [locale, messages, published]);

  const context = useMemo(
    () => ({
      configuration: published?.configuration || null,
      publicationVersion: published?.publication.version || null,
      locale,
      text(value: LocalizedPortalText | undefined, fallback = "") {
        return value?.[locale] || value?.en || value?.ar || fallback;
      },
      href(value: string) {
        return resolvePortalHref(value, locale);
      },
    }),
    [locale, published],
  );

  return (
    <PortalContext.Provider value={context}>
      <NextIntlClientProvider messages={mergedMessages} locale={locale} timeZone="UTC">
        {children}
      </NextIntlClientProvider>
    </PortalContext.Provider>
  );
}

export function usePortalExperience() {
  return useContext(PortalContext);
}
