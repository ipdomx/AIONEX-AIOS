"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  Bell,
  MessageSquare,
  CheckSquare,
  Zap,
  Globe,
  Moon,
  Sun,
  User,
  ChevronDown,
  LogOut,
  Settings,
  Shield,
  CreditCard,
  Command,
  X,
  AlertTriangle,
  Info,
  CheckCircle2,
  Menu,
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/components/providers/AuthProvider";
import { ownerNavigationItems } from "@/config/owner-navigation";
import { isOwnerRole } from "@/config/owner-access";

interface TopBarProps {
  sidebarCollapsed: boolean;
  mobile: boolean;
  onMenuOpen: () => void;
  onSearchOpen: () => void;
  onCommandOpen: () => void;
}

export default function TopBar({
  sidebarCollapsed,
  mobile,
  onMenuOpen,
  onSearchOpen,
  onCommandOpen,
}: TopBarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [language, setLanguage] = useState<"en" | "ar">("en");
  const ownerPage = ownerNavigationItems.find((item) => item.href === pathname);
  const currentPage =
    pathname === "/"
      ? "Overview"
      : (ownerPage?.label ??
        pathname
          .split("/")
          .filter(Boolean)
          .at(-1)
          ?.replace(/-/g, " ")
          .replace(/\b\w/g, (letter) => letter.toUpperCase()) ??
        "Dashboard");
  const displayName = user?.name ?? "AIONEX User";
  const displayEmail = user?.email ?? "";
  const displayRole = user?.role ?? "User";
  const canAccessOwner = isOwnerRole(user?.role);

  function navigate(href: string) {
    setNotificationsOpen(false);
    setProfileOpen(false);
    router.push(href);
  }

  async function signOut() {
    setProfileOpen(false);
    await logout();
    router.replace("/");
  }

  const notifications = [
    {
      id: "1",
      type: "warning" as const,
      title: "High CPU Usage",
      message: "Server prod-web-01 CPU usage exceeded 85%",
      time: "2 min ago",
      read: false,
    },
    {
      id: "2",
      type: "success" as const,
      title: "Deployment Complete",
      message: "Workflow 'Data Pipeline v2' deployed successfully",
      time: "15 min ago",
      read: false,
    },
    {
      id: "3",
      type: "info" as const,
      title: "New Agent Joined",
      message: "AI Agent 'Code Reviewer' is now active",
      time: "1 hour ago",
      read: true,
    },
    {
      id: "4",
      type: "error" as const,
      title: "Database Connection Failed",
      message: "PostgreSQL primary connection timeout",
      time: "2 hours ago",
      read: true,
    },
  ];

  const getNotificationIcon = (type: string) => {
    switch (type) {
      case "warning":
        return <AlertTriangle className="w-4 h-4 text-orange-400" />;
      case "error":
        return <X className="w-4 h-4 text-red-400" />;
      case "success":
        return <CheckCircle2 className="w-4 h-4 text-green-400" />;
      default:
        return <Info className="w-4 h-4 text-blue-400" />;
    }
  };

  return (
    <motion.header
      initial={false}
      animate={{ marginLeft: mobile ? 0 : sidebarCollapsed ? 72 : 280 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="fixed left-0 right-0 top-0 z-40 flex h-16 items-center border-b border-white/[0.06] px-4 glass-strong"
    >
      {/* Left Section */}
      <div className="flex items-center gap-4 flex-1">
        <button
          type="button"
          onClick={onMenuOpen}
          className="rounded-xl p-2 text-white/60 transition hover:bg-white/[0.06] md:hidden"
          aria-label="Open navigation"
        >
          <Menu className="h-[18px] w-[18px]" />
        </button>
        {/* Breadcrumb */}
        <nav className="hidden items-center gap-2 text-sm sm:flex">
          <span className="text-white/30">AIONEX</span>
          <ChevronDown className="w-3 h-3 text-white/20 rotate-[-90deg]" />
          <span className="text-white/60">{currentPage}</span>
        </nav>
      </div>

      {/* Center Section - Search */}
      <div className="hidden max-w-xl flex-1 md:block">
        <button
          onClick={onSearchOpen}
          className="w-full flex items-center gap-3 px-4 py-2 rounded-xl bg-white/[0.03] border border-white/[0.06] hover:bg-white/[0.05] hover:border-white/[0.1] transition-all duration-200 group"
        >
          <Search className="w-4 h-4 text-white/30 group-hover:text-white/50 transition-colors" />
          <span className="text-sm text-white/30 group-hover:text-white/50 transition-colors">
            Search anything...
          </span>
          <div className="ml-auto flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 rounded-md bg-white/[0.06] text-[10px] text-white/40 font-mono border border-white/[0.08]">
              ⇧⌘
            </kbd>
            <kbd className="px-1.5 py-0.5 rounded-md bg-white/[0.06] text-[10px] text-white/40 font-mono border border-white/[0.08]">
              K
            </kbd>
          </div>
        </button>
      </div>

      {/* Right Section */}
      <div className="flex items-center gap-2 flex-1 justify-end">
        <button
          type="button"
          onClick={onSearchOpen}
          className="rounded-xl p-2 transition-colors hover:bg-white/[0.06] md:hidden"
          aria-label="Open search"
        >
          <Search className="h-[18px] w-[18px] text-white/50" />
        </button>

        {/* Command Palette Button */}
        <button
          onClick={onCommandOpen}
          className="relative rounded-xl p-2 transition-colors hover:bg-white/[0.06]"
          title="Command Palette"
          aria-label="Open command palette"
        >
          <Command className="w-[18px] h-[18px] text-white/50" />
        </button>

        {canAccessOwner && (
          <>
            {/* Running Jobs */}
            <button
              onClick={() => navigate("/owner/realtime")}
              className="relative hidden rounded-xl p-2 transition-colors hover:bg-white/[0.06] lg:block"
              title="Open realtime monitoring"
            >
              <Zap className="h-[18px] w-[18px] text-white/50" />
              <span className="absolute right-1.5 top-1.5 h-2 w-2 animate-pulse rounded-full bg-electric-500" />
            </button>

            {/* Messages */}
            <button
              onClick={() => navigate("/owner/communications")}
              className="relative hidden rounded-xl p-2 transition-colors hover:bg-white/[0.06] lg:block"
              title="Open owner communications"
            >
              <MessageSquare className="h-[18px] w-[18px] text-white/50" />
              <span className="absolute right-1.5 top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-accent-red text-[9px] font-bold text-white">
                3
              </span>
            </button>
          </>
        )}

        {/* Tasks */}
        <button
          onClick={() => navigate("/tasks")}
          className="relative hidden rounded-xl p-2 transition-colors hover:bg-white/[0.06] md:block"
          title="Open tasks"
        >
          <CheckSquare className="w-[18px] h-[18px] text-white/50" />
          <span className="absolute top-1.5 right-1.5 w-4 h-4 rounded-full bg-accent-orange text-[9px] font-bold text-white flex items-center justify-center">
            5
          </span>
        </button>

        {/* Notifications */}
        {canAccessOwner && (
          <div className="relative">
            <button
              onClick={() => setNotificationsOpen(!notificationsOpen)}
              className="p-2 rounded-xl hover:bg-white/[0.06] transition-colors relative"
            >
              <Bell className="w-[18px] h-[18px] text-white/50" />
              <span className="absolute top-1.5 right-1.5 w-4 h-4 rounded-full bg-accent-red text-[9px] font-bold text-white flex items-center justify-center">
                2
              </span>
            </button>

            <AnimatePresence>
              {notificationsOpen && (
                <>
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setNotificationsOpen(false)}
                  />
                  <motion.div
                    initial={{ opacity: 0, y: 10, scale: 0.95 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 10, scale: 0.95 }}
                    transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                    className="absolute right-0 top-12 w-96 z-50 glass-card overflow-hidden"
                  >
                    <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
                      <span className="text-sm font-semibold text-white">
                        Notifications
                      </span>
                      <button
                        onClick={() => navigate("/owner/notifications")}
                        className="text-xs text-electric-400 transition-colors hover:text-electric-300"
                      >
                        Manage
                      </button>
                    </div>
                    <div className="max-h-96 overflow-y-auto">
                      {notifications.map((notification) => (
                        <button
                          type="button"
                          key={notification.id}
                          onClick={() => navigate("/owner/notifications")}
                          className={cn(
                            "flex w-full items-start gap-3 border-b border-white/[0.04] px-4 py-3 text-left transition-colors hover:bg-white/[0.03]",
                            !notification.read && "bg-white/[0.02]",
                          )}
                        >
                          <div className="mt-0.5">
                            {getNotificationIcon(notification.type)}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-white truncate">
                                {notification.title}
                              </span>
                              {!notification.read && (
                                <span className="w-1.5 h-1.5 rounded-full bg-electric-500 flex-shrink-0" />
                              )}
                            </div>
                            <p className="text-xs text-white/50 mt-0.5 line-clamp-2">
                              {notification.message}
                            </p>
                            <span className="text-[10px] text-white/30 mt-1">
                              {notification.time}
                            </span>
                          </div>
                        </button>
                      ))}
                    </div>
                    <div className="px-4 py-2 border-t border-white/[0.06]">
                      <button
                        onClick={() => navigate("/owner/notifications")}
                        className="w-full py-1 text-center text-xs text-white/40 transition-colors hover:text-white/70"
                      >
                        View all notifications
                      </button>
                    </div>
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </div>
        )}

        {/* Language */}
        <button
          onClick={() => setLanguage(language === "en" ? "ar" : "en")}
          className="hidden rounded-xl p-2 transition-colors hover:bg-white/[0.06] lg:block"
          title={language === "en" ? "Switch to Arabic" : "Switch to English"}
        >
          <Globe className="w-[18px] h-[18px] text-white/50" />
        </button>

        {/* Theme */}
        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="hidden rounded-xl p-2 transition-colors hover:bg-white/[0.06] lg:block"
        >
          {theme === "dark" ? (
            <Sun className="w-[18px] h-[18px] text-white/50" />
          ) : (
            <Moon className="w-[18px] h-[18px] text-white/50" />
          )}
        </button>

        {/* Divider */}
        <div className="hidden h-6 w-px bg-white/[0.08] sm:block" />

        {/* User Profile */}
        <div className="relative">
          <button
            onClick={() => setProfileOpen(!profileOpen)}
            className="flex items-center gap-2.5 px-2 py-1.5 rounded-xl hover:bg-white/[0.06] transition-colors"
          >
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center border border-white/[0.08]">
              <User className="w-4 h-4 text-blue-400" />
            </div>
            <div className="hidden lg:flex flex-col items-start">
              <span className="text-xs font-semibold text-white">
                {displayName}
              </span>
              <span className="text-[10px] text-white/40">{displayRole}</span>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-white/30" />
          </button>

          <AnimatePresence>
            {profileOpen && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setProfileOpen(false)}
                />
                <motion.div
                  initial={{ opacity: 0, y: 10, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 10, scale: 0.95 }}
                  transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                  className="absolute right-0 top-12 w-64 z-50 glass-card overflow-hidden"
                >
                  <div className="px-4 py-4 border-b border-white/[0.06]">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center border border-white/[0.08]">
                        <User className="w-5 h-5 text-blue-400" />
                      </div>
                      <div>
                        <span className="block text-sm font-semibold text-white">
                          {displayName}
                        </span>
                        <span className="text-xs text-white/40">
                          {displayEmail}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="py-1">
                    <button
                      onClick={() => navigate("/settings")}
                      className="flex w-full items-center gap-3 px-4 py-2 text-sm text-white/60 transition-colors hover:bg-white/[0.04] hover:text-white"
                    >
                      <User className="w-4 h-4" />
                      Profile
                    </button>
                    <button
                      onClick={() => navigate("/settings")}
                      className="flex w-full items-center gap-3 px-4 py-2 text-sm text-white/60 transition-colors hover:bg-white/[0.04] hover:text-white"
                    >
                      <Settings className="w-4 h-4" />
                      Settings
                    </button>
                    <button
                      onClick={() =>
                        navigate(canAccessOwner ? "/owner/access" : "/settings")
                      }
                      className="flex w-full items-center gap-3 px-4 py-2 text-sm text-white/60 transition-colors hover:bg-white/[0.04] hover:text-white"
                    >
                      <Shield className="w-4 h-4" />
                      Security
                    </button>
                    <button
                      onClick={() =>
                        navigate(
                          canAccessOwner ? "/owner/billing" : "/settings",
                        )
                      }
                      className="flex w-full items-center gap-3 px-4 py-2 text-sm text-white/60 transition-colors hover:bg-white/[0.04] hover:text-white"
                    >
                      <CreditCard className="w-4 h-4" />
                      Billing
                    </button>
                  </div>
                  <div className="border-t border-white/[0.06] py-1">
                    <button
                      onClick={() => void signOut()}
                      className="flex w-full items-center gap-3 px-4 py-2 text-sm text-red-400 transition-colors hover:bg-red-500/5 hover:text-red-300"
                    >
                      <LogOut className="w-4 h-4" />
                      Sign Out
                    </button>
                  </div>
                </motion.div>
              </>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.header>
  );
}

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}
