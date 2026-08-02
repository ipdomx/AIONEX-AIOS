"use client";

import { Languages } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useTransition } from "react";
import { locales, type Locale } from "@/i18n";

const labels: Record<Locale, string> = {
  ar: "العربية",
  en: "English",
  fr: "Français",
  de: "Deutsch",
  es: "Español",
  tr: "Türkçe"
};

export function LanguageSwitcher() {
  const locale = useLocale() as Locale;
  const t = useTranslations("nav");
  const pathname = usePathname();
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function changeLocale(nextLocale: string) {
    if (!locales.includes(nextLocale as Locale)) return;
    const segments = pathname.split("/");
    segments[1] = nextLocale;
    startTransition(() =>
      router.replace(segments.join("/") || `/${nextLocale}`)
    );
  }

  return (
    <label className="relative inline-flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-xs text-white/65 transition hover:bg-white/[0.07]">
      <Languages className="h-4 w-4 text-electric-200" aria-hidden="true" />
      <span className="sr-only">{t("language")}</span>
      <select
        value={locale}
        onChange={(event) => changeLocale(event.target.value)}
        disabled={pending}
        aria-label={t("language")}
        className="cursor-pointer appearance-none bg-transparent pe-4 text-xs font-medium text-white outline-none disabled:opacity-50"
      >
        {locales.map((item) => (
          <option key={item} value={item} className="bg-ink-800 text-white">
            {labels[item]}
          </option>
        ))}
      </select>
      <span className="pointer-events-none absolute end-2 text-[8px] text-white/30">
        ▼
      </span>
    </label>
  );
}
