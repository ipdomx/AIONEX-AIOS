"use client";

import { LogOut, Menu, UserRound, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { Brand } from "@/components/brand";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

export function Navbar() {
  const t = useTranslations("nav");
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isLoading, logout } = useAuth();
  const [open, setOpen] = useState(false);

  const links = [
    { href: `/${locale}`, label: t("home") },
    { href: `/${locale}/about`, label: t("about") },
    { href: `/${locale}/contact`, label: t("contact") }
  ];

  async function signOut() {
    await logout();
    setOpen(false);
    router.push(`/${locale}/login`);
  }

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-white/[0.07] bg-ink-950/80 backdrop-blur-2xl">
      <nav className="page-shell flex h-20 items-center justify-between" aria-label={t("mainNavigation")}>
        <span onClick={() => setOpen(false)}>
          <Brand locale={locale} />
        </span>

        <div className="hidden items-center gap-1 lg:flex">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "rounded-lg px-4 py-2 text-sm transition",
                pathname === link.href
                  ? "bg-white/[0.07] text-white"
                  : "text-white/55 hover:bg-white/[0.05] hover:text-white"
              )}
            >
              {link.label}
            </Link>
          ))}
        </div>

        <div className="hidden items-center gap-2 lg:flex">
          <ThemeToggle label={t("theme")} />
          <LanguageSwitcher />
          {!isLoading && isAuthenticated ? (
            <>
              <Link href={`/${locale}/projects`} className="rounded-xl px-3 py-2 text-sm text-white/65 hover:text-white">
                {t("projects")}
              </Link>
              <Link
                href={`/${locale}/profile`}
                className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-white/70 hover:bg-white/[0.08] hover:text-white"
              >
                <UserRound className="h-4 w-4" aria-hidden="true" />
                {t("profile")}
              </Link>
              <Button variant="ghost" size="sm" onClick={() => void signOut()} aria-label={t("logout")}>
                <LogOut className="h-4 w-4" aria-hidden="true" />
              </Button>
            </>
          ) : (
            !isLoading && (
              <>
                <Link href={`/${locale}/login`} className="rounded-xl px-4 py-2 text-sm font-medium text-white/70 hover:text-white">
                  {t("login")}
                </Link>
                <Link href={`/${locale}/register`} className="inline-flex h-10 items-center rounded-xl border border-electric-300/30 bg-gradient-to-r from-electric-500 to-violet-500 px-4 text-sm font-semibold text-white shadow-lg shadow-electric-500/15 transition hover:brightness-110">
                  {t("register")}
                </Link>
              </>
            )
          )}
        </div>

        <button
          type="button"
          className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-white lg:hidden"
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
          aria-label={open ? t("closeMenu") : t("openMenu")}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </nav>

      {open && (
        <div className="border-t border-white/[0.07] bg-ink-950/95 px-4 py-5 backdrop-blur-2xl lg:hidden">
          <div className="mx-auto flex max-w-7xl flex-col gap-2">
            {links.map((link) => (
              <Link key={link.href} href={link.href} onClick={() => setOpen(false)} className="rounded-xl px-4 py-3 text-sm text-white/70 hover:bg-white/[0.06] hover:text-white">
                {link.label}
              </Link>
            ))}
            {isAuthenticated && (
              <>
                <Link href={`/${locale}/projects`} onClick={() => setOpen(false)} className="rounded-xl px-4 py-3 text-sm text-white/70 hover:bg-white/[0.06]">
                  {t("projects")}
                </Link>
                <Link href={`/${locale}/profile`} onClick={() => setOpen(false)} className="rounded-xl px-4 py-3 text-sm text-white/70 hover:bg-white/[0.06]">
                  {t("profile")}
                </Link>
              </>
            )}
            <div className="my-2 h-px bg-white/[0.07]" />
            <ThemeToggle label={t("theme")} />
            <LanguageSwitcher />
            {!isLoading && isAuthenticated ? (
              <Button variant="secondary" className="mt-2 w-full" onClick={() => void signOut()}>
                <LogOut className="h-4 w-4" aria-hidden="true" />
                {t("logout")}
              </Button>
            ) : (
              !isLoading && (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <Link href={`/${locale}/login`} onClick={() => setOpen(false)} className="inline-flex h-11 items-center justify-center rounded-xl border border-white/10 text-sm font-semibold text-white/75">
                    {t("login")}
                  </Link>
                  <Link href={`/${locale}/register`} onClick={() => setOpen(false)} className="inline-flex h-11 items-center justify-center rounded-xl bg-gradient-to-r from-electric-500 to-violet-500 text-sm font-semibold text-white">
                    {t("register")}
                  </Link>
                </div>
              )
            )}
          </div>
        </div>
      )}
    </header>
  );
}
