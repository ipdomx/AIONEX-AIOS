"use client";

import {
  Bell,
  Box,
  CalendarDays,
  CreditCard,
  LayoutDashboard,
  LifeBuoy,
  Megaphone,
  Radio,
  LogOut,
  Menu,
  Share2,
  ShieldCheck,
  Sparkles,
  SquarePen,
  UserRound,
  X,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Brand } from "@/components/brand";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/use-auth";
import { getPaidCampaignReadiness, getSecurityLabAccess } from "@/lib/api";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";
import { cn } from "@/lib/utils";

export function Navbar() {
  const t = useTranslations("nav");
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isLoading, logout } = useAuth();
  const { configuration, text, href: portalHref } = usePortalExperience();
  const [open, setOpen] = useState(false);
  const [securityLabVisible, setSecurityLabVisible] = useState(false);
  const [campaignsVisible, setCampaignsVisible] = useState(false);

  useEffect(() => {
    if (!isAuthenticated) {
      setSecurityLabVisible(false);
      setCampaignsVisible(false);
      return;
    }
    let cancelled = false;
    void getSecurityLabAccess()
      .then((access) => {
        if (!cancelled)
          setSecurityLabVisible(
            access.enabled &&
              (access.granted ||
                Boolean(access.upgrade_required) ||
                Boolean(access.reports_available)),
          );
      })
      .catch(() => {
        if (!cancelled) setSecurityLabVisible(false);
      });
    void getPaidCampaignReadiness()
      .then((access) => {
        if (!cancelled) setCampaignsVisible(access.campaigns_visible);
      })
      .catch(() => {
        if (!cancelled) setCampaignsVisible(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  const fallbackLinks = [
    { id: "home", href: `/${locale}`, label: t("home"), external: false },
    {
      id: "about",
      href: `/${locale}/about`,
      label: t("about"),
      external: false,
    },
    {
      id: "pricing",
      href: `/${locale}/pricing`,
      label: t.has("pricing") ? t("pricing") : "Pricing",
      external: false,
    },
    {
      id: "contact",
      href: `/${locale}/contact`,
      label: t("contact"),
      external: false,
    },
  ];
  const links = configuration
    ? configuration.navigation
        .filter((item) => item.enabled)
        .filter(
          (item) =>
            item.audience === "all" ||
            (item.audience === "guest" ? !isAuthenticated : isAuthenticated),
        )
        .sort((a, b) => a.order - b.order)
        .map((item) => ({
          id: item.id,
          href: portalHref(item.href),
          label: text(item.label, item.id),
          external: item.external,
        }))
    : fallbackLinks;

  const currentPath = pathname.replace(/\/$/, "");
  const isActive = (target: string) => currentPath === target.replace(/\/$/, "");

  function NavigationLink({
    link,
    mobile = false,
  }: {
    link: (typeof links)[number];
    mobile?: boolean;
  }) {
    const active = isActive(link.href);
    const className = mobile
      ? "nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
      : cn(
          "nav-link rounded-xl px-4 py-2 text-sm font-medium",
          !active && "hover:bg-white/[0.04]",
        );
    if (link.external || link.href.startsWith("https://")) {
      return (
        <a
          href={link.href}
          target="_blank"
          rel="noreferrer"
          className={className}
          data-active={active ? "true" : undefined}
          onClick={() => mobile && setOpen(false)}
        >
          {link.label}
        </a>
      );
    }
    return (
      <Link
        href={link.href}
        className={className}
        data-active={active ? "true" : undefined}
        onClick={() => mobile && setOpen(false)}
      >
        {link.label}
      </Link>
    );
  }

  async function signOut() {
    await logout();
    setOpen(false);
    router.push(`/${locale}/login`);
  }

  return (
    <header className="relative border-b border-white/[0.08] bg-obsidian-950/80 backdrop-blur-xl">
      <nav
        className="page-shell flex h-20 items-center justify-between"
        aria-label={t("mainNavigation")}
      >
        <span onClick={() => setOpen(false)}>
          <Brand locale={locale} />
        </span>

        <div className="hidden items-center gap-1 lg:flex">
          {links.map((link) => (
            <NavigationLink key={link.id} link={link} />
          ))}
        </div>

        <div className="hidden items-center gap-2 lg:flex">
          <ThemeToggle label={t("theme")} />
          <LanguageSwitcher />
          {!isLoading && isAuthenticated ? (
            <>
              <Link
                href={`/${locale}/dashboard`}
                className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/dashboard`) ? "true" : undefined}
              >
                <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
                {t("dashboard")}
              </Link>
              <Link
                href={`/${locale}/projects`}
                className="nav-link rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/projects`) ? "true" : undefined}
              >
                {t("projects")}
              </Link>
              <Link href={`/${locale}/conversations`} className="nav-link rounded-xl px-3 py-2 text-sm" data-active={isActive(`/${locale}/conversations`) ? "true" : undefined}>
                {t("conversations")}
              </Link>
              <Link
                href={`/${locale}/studio`}
                className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/studio`) ? "true" : undefined}
              >
                <Sparkles className="h-4 w-4" aria-hidden="true" />
                {t("studio")}
              </Link>
              <Link
                href={`/${locale}/3d`}
                className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/3d`) ? "true" : undefined}
              >
                <Box className="h-4 w-4" aria-hidden="true" />
                {t("threeD")}
              </Link>
              <Link
                href={`/${locale}/realtime`}
                className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/realtime`) ? "true" : undefined}
              >
                <Radio className="h-4 w-4" aria-hidden="true" />
                {t("realtime")}
              </Link>
              <Link
                href={`/${locale}/social`}
                className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/social`) ? "true" : undefined}
              >
                <Share2 className="h-4 w-4" aria-hidden="true" />
                {t("social")}
              </Link>
              <Link
                href={`/${locale}/social/compose`}
                className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/social/compose`) ? "true" : undefined}
              >
                <SquarePen className="h-4 w-4" aria-hidden="true" />
                {t("socialCompose")}
              </Link>
              <Link
                href={`/${locale}/social/calendar`}
                className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/social/calendar`) ? "true" : undefined}
              >
                <CalendarDays className="h-4 w-4" aria-hidden="true" />
                {t("socialCalendar")}
              </Link>
              {campaignsVisible && (
                <Link
                  href={`/${locale}/campaigns`}
                  className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                  data-active={isActive(`/${locale}/campaigns`) ? "true" : undefined}
                >
                  <Megaphone className="h-4 w-4" aria-hidden="true" />
                  {t("campaigns")}
                </Link>
              )}
              <Link
                href={`/${locale}/billing`}
                className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/billing`) ? "true" : undefined}
              >
                <CreditCard className="h-4 w-4" aria-hidden="true" />
                {t("billing")}
              </Link>
              {securityLabVisible && (
                <Link
                  href={`/${locale}/security-lab`}
                  className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                  data-active={isActive(`/${locale}/security-lab`) ? "true" : undefined}
                >
                  <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                  {t("securityLab")}
                </Link>
              )}
              <Link
                href={`/${locale}/notifications`}
                className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/notifications`) ? "true" : undefined}
              >
                <Bell className="h-4 w-4" aria-hidden="true" />
                {t("notifications")}
              </Link>
              <Link
                href={`/${locale}/support`}
                className="nav-link inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
                data-active={isActive(`/${locale}/support`) ? "true" : undefined}
              >
                <LifeBuoy className="h-4 w-4" aria-hidden="true" />
                {t("support")}
              </Link>
              <Link
                href={`/${locale}/profile`}
                className="portal-secondary-button inline-flex h-10 items-center gap-2 px-3 text-sm"
              >
                <UserRound className="h-4 w-4" aria-hidden="true" />
                {t("profile")}
              </Link>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void signOut()}
                aria-label={t("logout")}
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
              </Button>
            </>
          ) : (
            !isLoading && (
              <>
                <Link
                  href={`/${locale}/login`}
                  className="nav-link rounded-xl px-4 py-2 text-sm font-medium"
                >
                  {t("login")}
                </Link>
                <Link
                  href={`/${locale}/register`}
                  className="portal-primary-button inline-flex h-10 items-center px-4 text-sm font-semibold text-white"
                >
                  {t("register")}
                </Link>
              </>
            )
          )}
        </div>

        <button
          type="button"
          className="icon-button h-11 w-11 lg:hidden"
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
          aria-label={open ? t("closeMenu") : t("openMenu")}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </nav>

      {open && (
        <div className="border-t border-white/[0.08] bg-obsidian-950/95 px-4 py-5 backdrop-blur-xl lg:hidden">
          <div className="mx-auto flex max-w-7xl flex-col gap-2">
            {links.map((link) => (
              <NavigationLink key={link.id} link={link} mobile />
            ))}
            {isAuthenticated && (
              <>
                <Link
                  href={`/${locale}/dashboard`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/dashboard`) ? "true" : undefined}
                >
                  {t("dashboard")}
                </Link>
                <Link
                  href={`/${locale}/projects`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/projects`) ? "true" : undefined}
                >
                  {t("projects")}
                </Link>
                <Link href={`/${locale}/conversations`} onClick={() => setOpen(false)} className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/conversations`) ? "true" : undefined}>
                  {t("conversations")}
                </Link>
                <Link
                  href={`/${locale}/studio`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/studio`) ? "true" : undefined}
                >
                  {t("studio")}
                </Link>
                <Link
                  href={`/${locale}/3d`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/3d`) ? "true" : undefined}
                >
                  {t("threeD")}
                </Link>
                <Link
                  href={`/${locale}/realtime`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/realtime`) ? "true" : undefined}
                >
                  {t("realtime")}
                </Link>
                <Link
                  href={`/${locale}/social`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/social`) ? "true" : undefined}
                >
                  {t("social")}
                </Link>
                <Link
                  href={`/${locale}/social/compose`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/social/compose`) ? "true" : undefined}
                >
                  {t("socialCompose")}
                </Link>
                <Link
                  href={`/${locale}/social/calendar`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/social/calendar`) ? "true" : undefined}
                >
                  {t("socialCalendar")}
                </Link>
                {campaignsVisible && (
                  <Link
                    href={`/${locale}/campaigns`}
                    onClick={() => setOpen(false)}
                    className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                    data-active={isActive(`/${locale}/campaigns`) ? "true" : undefined}
                  >
                    {t("campaigns")}
                  </Link>
                )}
                <Link
                  href={`/${locale}/billing`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/billing`) ? "true" : undefined}
                >
                  {t("billing")}
                </Link>
                {securityLabVisible && (
                  <Link
                    href={`/${locale}/security-lab`}
                    onClick={() => setOpen(false)}
                    className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                    data-active={isActive(`/${locale}/security-lab`) ? "true" : undefined}
                  >
                    {t("securityLab")}
                  </Link>
                )}
                <Link
                  href={`/${locale}/notifications`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/notifications`) ? "true" : undefined}
                >
                  {t("notifications")}
                </Link>
                <Link
                  href={`/${locale}/support`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/support`) ? "true" : undefined}
                >
                  {t("support")}
                </Link>
                <Link
                  href={`/${locale}/profile`}
                  onClick={() => setOpen(false)}
                  className="nav-link rounded-xl px-4 py-3 text-sm hover:bg-white/[0.06]"
                  data-active={isActive(`/${locale}/profile`) ? "true" : undefined}
                >
                  {t("profile")}
                </Link>
              </>
            )}
            <div className="my-2 h-px bg-white/[0.07]" />
            <ThemeToggle label={t("theme")} />
            <LanguageSwitcher />
            {!isLoading && isAuthenticated ? (
              <Button
                variant="secondary"
                className="mt-2 w-full"
                onClick={() => void signOut()}
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
                {t("logout")}
              </Button>
            ) : (
              !isLoading && (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <Link
                    href={`/${locale}/login`}
                    onClick={() => setOpen(false)}
                    className="portal-secondary-button inline-flex h-11 items-center justify-center text-sm font-semibold"
                  >
                    {t("login")}
                  </Link>
                  <Link
                    href={`/${locale}/register`}
                    onClick={() => setOpen(false)}
                    className="portal-primary-button inline-flex h-11 items-center justify-center text-sm font-semibold text-white"
                  >
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
