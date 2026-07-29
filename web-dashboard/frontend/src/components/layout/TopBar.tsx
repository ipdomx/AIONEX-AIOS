"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ChevronDown,
  Command,
  CreditCard,
  LogOut,
  Menu,
  Search,
  Settings,
  Shield,
  User,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/providers/AuthProvider";
import { ownerNavigationItems } from "@/config/owner-navigation";

interface TopBarProps {
  sidebarCollapsed: boolean;
  mobile: boolean;
  onMenuOpen: () => void;
  onSearchOpen: () => void;
  onCommandOpen: () => void;
}

function routeLabel(pathname: string): string {
  if (pathname === "/") return "Overview";
  if (pathname === "/owner") return "Owner Center";

  const ownerItem = ownerNavigationItems.find((item) => item.href === pathname);
  if (ownerItem) return ownerItem.label;

  const segment = pathname.split("/").filter(Boolean).at(-1) ?? "Dashboard";
  return segment
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export default function TopBar({
  sidebarCollapsed,
  mobile,
  onMenuOpen,
  onSearchOpen,
  onCommandOpen,
}: TopBarProps) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [profileOpen, setProfileOpen] = useState(false);
  const pageLabel = useMemo(() => routeLabel(pathname), [pathname]);
  const isSuperOwner = user?.role === "Super Owner";

  async function signOut() {
    setProfileOpen(false);
    try {
      await logout();
    } catch {
      // Local session state is cleared by AuthProvider even if the API is unavailable.
    }
  }

  return (
    <header
      className="glass-strong fixed left-0 right-0 top-0 z-40 flex h-16 items-center border-b border-white/[0.06] px-3 transition-[margin] duration-300 sm:px-4"
      style={{
        marginLeft: mobile ? "0px" : sidebarCollapsed ? "72px" : "280px",
      }}
    >
      {mobile && (
        <button
          type="button"
          onClick={onMenuOpen}
          className="mr-2 rounded-xl p-2 transition hover:bg-white/[0.06]"
          aria-label="Open navigation"
        >
          <Menu className="h-[18px] w-[18px] text-white/50" />
        </button>
      )}
      <nav className="hidden min-w-0 flex-1 items-center gap-2 text-sm sm:flex">
        <span className="text-white/30">AIONEX</span>
        <span className="text-white/20">/</span>
        <span className="truncate text-white/60">{pageLabel}</span>
      </nav>

      <div className="hidden max-w-xl flex-1 md:block">
        <button
          type="button"
          onClick={onSearchOpen}
          className="group flex w-full items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.03] px-4 py-2 transition hover:border-white/[0.1] hover:bg-white/[0.05]"
        >
          <Search className="h-4 w-4 text-white/30 transition-colors group-hover:text-white/50" />
          <span className="text-sm text-white/30 transition-colors group-hover:text-white/50">
            Search pages and Owner modules…
          </span>
          <kbd className="ml-auto rounded-md border border-white/[0.08] bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-white/40">
            ⇧⌘K
          </kbd>
        </button>
      </div>

      <div className="ml-auto flex flex-1 items-center justify-end gap-1 sm:gap-2">
        <button
          type="button"
          onClick={onSearchOpen}
          className="rounded-xl p-2 transition hover:bg-white/[0.06] md:hidden"
          aria-label="Search pages"
        >
          <Search className="h-[18px] w-[18px] text-white/50" />
        </button>
        <button
          type="button"
          onClick={onCommandOpen}
          className="rounded-xl p-2 transition hover:bg-white/[0.06]"
          aria-label="Open command palette"
        >
          <Command className="h-[18px] w-[18px] text-white/50" />
        </button>

        <div className="relative">
          <button
            type="button"
            onClick={() => setProfileOpen((current) => !current)}
            className="flex items-center gap-2.5 rounded-xl px-2 py-1.5 transition hover:bg-white/[0.06]"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.08] bg-gradient-to-br from-blue-500/20 to-purple-500/20">
              <User className="h-4 w-4 text-blue-400" />
            </div>
            <div className="hidden flex-col items-start lg:flex">
              <span className="max-w-36 truncate text-xs font-semibold text-white">
                {user?.name ?? "Signed-in user"}
              </span>
              <span className="text-[10px] text-white/40">
                {user?.role ?? "Member"}
              </span>
            </div>
            <ChevronDown className="hidden h-3.5 w-3.5 text-white/30 sm:block" />
          </button>

          <AnimatePresence>
            {profileOpen && (
              <>
                <button
                  type="button"
                  aria-label="Close profile menu"
                  className="fixed inset-0 z-40 cursor-default"
                  onClick={() => setProfileOpen(false)}
                />
                <motion.div
                  initial={{ opacity: 0, y: 10, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 10, scale: 0.95 }}
                  transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                  className="glass-card absolute right-0 top-12 z-50 w-64 overflow-hidden"
                >
                  <div className="border-b border-white/[0.06] px-4 py-4">
                    <span className="block truncate text-sm font-semibold text-white">
                      {user?.name ?? "Signed-in user"}
                    </span>
                    <span className="block truncate text-xs text-white/40">
                      {user?.email}
                    </span>
                  </div>
                  <div className="py-1">
                    <Link
                      href="/settings"
                      onClick={() => setProfileOpen(false)}
                      className="flex items-center gap-3 px-4 py-2 text-sm text-white/60 transition hover:bg-white/[0.04] hover:text-white"
                    >
                      <Settings className="h-4 w-4" />
                      Settings
                    </Link>
                    {isSuperOwner && (
                      <>
                        <Link
                          href="/owner/access"
                          onClick={() => setProfileOpen(false)}
                          className="flex items-center gap-3 px-4 py-2 text-sm text-white/60 transition hover:bg-white/[0.04] hover:text-white"
                        >
                          <Shield className="h-4 w-4" />
                          Owner access
                        </Link>
                        <Link
                          href="/owner/billing"
                          onClick={() => setProfileOpen(false)}
                          className="flex items-center gap-3 px-4 py-2 text-sm text-white/60 transition hover:bg-white/[0.04] hover:text-white"
                        >
                          <CreditCard className="h-4 w-4" />
                          Billing
                        </Link>
                      </>
                    )}
                  </div>
                  <div className="border-t border-white/[0.06] py-1">
                    <button
                      type="button"
                      onClick={() => void signOut()}
                      className="flex w-full items-center gap-3 px-4 py-2 text-sm text-red-400 transition hover:bg-red-500/5 hover:text-red-300"
                    >
                      <LogOut className="h-4 w-4" />
                      Sign out
                    </button>
                  </div>
                </motion.div>
              </>
            )}
          </AnimatePresence>
        </div>
      </div>
    </header>
  );
}
