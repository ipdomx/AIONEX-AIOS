import { LockKeyhole, ShieldCheck } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";
import Link from "next/link";
import { Brand } from "@/components/brand";

export async function Footer() {
  const t = await getTranslations("footer");
  const nav = await getTranslations("nav");
  const locale = await getLocale();
  return (
    <footer className="border-t border-white/[0.07] bg-black/20">
      <div className="page-shell grid gap-10 py-12 md:grid-cols-[1.4fr_1fr_1fr]">
        <div className="max-w-md">
          <Brand locale={locale} />
          <p className="mt-5 text-sm leading-7 text-white/45">
            {t("description")}
          </p>
          <div className="mt-5 inline-flex items-center gap-2 text-xs text-emerald-200/70">
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            {t("security")}
          </div>
        </div>
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-white/35">
            {t("navigation")}
          </p>
          <div className="mt-4 flex flex-col gap-3 text-sm text-white/55">
            <Link href={`/${locale}`} className="hover:text-white">
              {nav("home")}
            </Link>
            <Link href={`/${locale}/about`} className="hover:text-white">
              {nav("about")}
            </Link>
            <Link href={`/${locale}/contact`} className="hover:text-white">
              {nav("contact")}
            </Link>
            <Link
              href={`/${locale}/legal/privacy`}
              className="hover:text-white"
            >
              {t("privacy")}
            </Link>
            <Link href={`/${locale}/legal/terms`} className="hover:text-white">
              {t("terms")}
            </Link>
          </div>
        </div>
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-white/35">
            {t("access")}
          </p>
          <div className="mt-4 inline-flex items-center gap-2 text-sm text-white/55">
            <LockKeyhole className="h-4 w-4" aria-hidden="true" />
            {t("privateGateway")}
          </div>
        </div>
      </div>
      <div className="border-t border-white/[0.06] py-5 text-center text-xs text-white/30">
        © {new Date().getUTCFullYear()} AIONEX AIOS. {t("rights")}
      </div>
    </footer>
  );
}
