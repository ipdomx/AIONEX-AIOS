"use client";

import { LockKeyhole, ShieldCheck } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { Brand } from "@/components/brand";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";
import type { PortalNavigationItem } from "@/types/portal";

export function Footer() {
  const t = useTranslations("footer");
  const nav = useTranslations("nav");
  const locale = useLocale();
  const { configuration, text, href } = usePortalExperience();
  const footer = configuration?.footer;
  if (footer && !footer.enabled) return null;
  const fallbackLinks: PortalNavigationItem[] = [
    { id: "home", href: "/", label: { ar: nav("home"), en: nav("home"), fr: nav("home"), de: nav("home"), es: nav("home"), tr: nav("home") }, enabled: true, order: 10, audience: "all", external: false },
    { id: "about", href: "/about", label: { ar: nav("about"), en: nav("about"), fr: nav("about"), de: nav("about"), es: nav("about"), tr: nav("about") }, enabled: true, order: 20, audience: "all", external: false },
    { id: "contact", href: "/contact", label: { ar: nav("contact"), en: nav("contact"), fr: nav("contact"), de: nav("contact"), es: nav("contact"), tr: nav("contact") }, enabled: true, order: 30, audience: "all", external: false },
  ];
  const columns = footer?.columns || [
    {
      id: "navigation",
      title: { ar: t("navigation"), en: t("navigation"), fr: t("navigation"), de: t("navigation"), es: t("navigation"), tr: t("navigation") },
      links: fallbackLinks,
    },
  ];
  return (
    <footer className="border-t border-white/[0.07] bg-black/20">
      <div className="page-shell grid gap-10 py-12 md:grid-cols-[1.4fr_1fr_1fr]">
        <div className="max-w-md">
          <Brand locale={locale} />
          <p className="mt-5 text-sm leading-7 text-white/45">
            {text(footer?.description, t("description"))}
          </p>
          <div className="mt-5 inline-flex items-center gap-2 text-xs text-emerald-200/70">
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            {text(footer?.security_note, t("security"))}
          </div>
        </div>
        {columns.slice(0, 2).map((column, columnIndex) => (
          <div key={column.id}>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-white/35">
              {text(column.title, columnIndex === 0 ? t("navigation") : t("access"))}
            </p>
            <div className="mt-4 flex flex-col gap-3 text-sm text-white/55">
              {column.links
                .filter((item) => item.enabled)
                .sort((a, b) => a.order - b.order)
                .map((item) => {
                  const fallback: Record<string, string> = {
                    home: nav("home"),
                    about: nav("about"),
                    contact: nav("contact"),
                    privacy: t("privacy"),
                    terms: t("terms"),
                  };
                  const label = text(item.label, fallback[item.id.replace("footer-", "")] || item.id);
                  const target = href(item.href);
                  return item.external || target.startsWith("https://") ? (
                    <a key={item.id} href={target} target="_blank" rel="noreferrer" className="hover:text-white">{label}</a>
                  ) : (
                    <Link key={item.id} href={target} className="hover:text-white">{label}</Link>
                  );
                })}
            </div>
          </div>
        ))}
        {columns.length < 2 && (
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-white/35">{t("access")}</p>
            <div className="mt-4 inline-flex items-center gap-2 text-sm text-white/55">
              <LockKeyhole className="h-4 w-4" aria-hidden="true" />{t("privateGateway")}
            </div>
          </div>
        )}
      </div>
      <div className="border-t border-white/[0.06] py-5 text-center text-xs text-white/30">
        © {new Date().getUTCFullYear()} {configuration?.branding.site_name || "AIONEX AIOS"}. {text(footer?.copyright_text, t("rights"))}
      </div>
    </footer>
  );
}
