"use client";

import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  Users,
  Bot,
  Brain,
  Workflow,
  Server,
  Database,
  Shield,
  FileText,
  Settings,
  Bell,
  Search,
  ChevronRight,
  ChevronLeft,
  Building2,
  Briefcase,
  Layers,
  Activity,
  Lock,
  CreditCard,
  Calendar,
  CheckSquare,
  MessageSquare,
  Zap,
  BookOpen,
  Cpu,
  HardDrive,
  Globe,
  Terminal,
  BarChart3,
  FolderOpen,
  Sparkles,
  Command,
  Pin,
  Clock,
  Star,
  MoreHorizontal,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const mainNavSections = [
  {
    id: "overview",
    label: "Overview",
    icon: LayoutDashboard,
    href: "/",
  },
  {
    id: "projects",
    label: "Projects",
    icon: FolderOpen,
    href: "/projects",
    badge: 12,
  },
  {
    id: "ai",
    label: "AI",
    icon: Sparkles,
    children: [
      { id: "ai-providers", label: "Providers", icon: Zap, href: "/ai/providers" },
      { id: "ai-agents", label: "Agents", icon: Bot, href: "/ai/agents", badge: 8 },
      { id: "ai-models", label: "Models", icon: Brain, href: "/ai/models" },
      { id: "ai-usage", label: "Usage", icon: BarChart3, href: "/ai/usage" },
    ],
  },
  {
    id: "workflows",
    label: "Workflows",
    icon: Workflow,
    href: "/workflows",
    badge: 24,
  },
  {
    id: "knowledge",
    label: "Knowledge",
    icon: BookOpen,
    href: "/knowledge",
  },
  {
    id: "infrastructure",
    label: "Infrastructure",
    icon: Server,
    children: [
      { id: "infra-servers", label: "Servers", icon: Cpu, href: "/infrastructure/servers", badge: 6 },
      { id: "infra-containers", label: "Containers", icon: Layers, href: "/infrastructure/containers" },
      { id: "infra-kubernetes", label: "Kubernetes", icon: Globe, href: "/infrastructure/kubernetes" },
      { id: "infra-databases", label: "Databases", icon: Database, href: "/infrastructure/databases" },
      { id: "infra-redis", label: "Redis", icon: Zap, href: "/infrastructure/redis" },
      { id: "infra-queues", label: "Queues", icon: Terminal, href: "/infrastructure/queues" },
    ],
  },
  {
    id: "monitoring",
    label: "Monitoring",
    icon: Activity,
    children: [
      { id: "mon-metrics", label: "Metrics", icon: BarChart3, href: "/monitoring/metrics" },
      { id: "mon-logs", label: "Logs", icon: FileText, href: "/monitoring/logs" },
      { id: "mon-alerts", label: "Alerts", icon: Bell, href: "/monitoring/alerts", badge: 3 },
      { id: "mon-events", label: "Events", icon: Clock, href: "/monitoring/events" },
    ],
  },
  {
    id: "security",
    label: "Security",
    icon: Shield,
    children: [
      { id: "sec-threats", label: "Threat Center", icon: Lock, href: "/security/threats" },
      { id: "sec-audit", label: "Audit", icon: FileText, href: "/security/audit" },
      { id: "sec-sessions", label: "Sessions", icon: Globe, href: "/security/sessions" },
      { id: "sec-policies", label: "Policies", icon: Shield, href: "/security/policies" },
    ],
  },
  {
    id: "users",
    label: "Users",
    icon: Users,
    children: [
      { id: "users-list", label: "All Users", icon: Users, href: "/users" },
      { id: "users-orgs", label: "Organizations", icon: Building2, href: "/users/organizations" },
      { id: "users-teams", label: "Teams", icon: Briefcase, href: "/users/teams" },
      { id: "users-roles", label: "Roles", icon: Lock, href: "/users/roles" },
      { id: "users-permissions", label: "Permissions", icon: Shield, href: "/users/permissions" },
    ],
  },
  {
    id: "tasks",
    label: "Tasks",
    icon: CheckSquare,
    href: "/tasks",
    badge: 15,
  },
  {
    id: "meetings",
    label: "Meetings",
    icon: Calendar,
    href: "/meetings",
  },
  {
    id: "reports",
    label: "Reports",
    icon: BarChart3,
    href: "/reports",
  },
];

const bottomNavSections = [
  {
    id: "settings",
    label: "Settings",
    icon: Settings,
    href: "/settings",
  },
];

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();
  const [expandedSections, setExpandedSections] = useState<string[]>(["ai", "infrastructure"]);
  const [favorites] = useState(["ai-agents", "infra-servers", "mon-alerts"]);
  const [recentPages] = useState(["Projects", "AI Agents", "Server-01"]);

  const toggleSection = useCallback((sectionId: string) => {
    setExpandedSections((prev) =>
      prev.includes(sectionId) ? prev.filter((id) => id !== sectionId) : [...prev, sectionId]
    );
  }, []);

  const isActive = useCallback(
    (href: string) => {
      if (href === "/") return pathname === "/";
      return pathname.startsWith(href);
    },
    [pathname]
  );

  return (
    <motion.aside
      initial={false}
      animate={{ width: collapsed ? 72 : 280 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="fixed left-0 top-0 h-screen z-50 flex flex-col glass-strong border-r border-white/[0.06]"
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 h-16 border-b border-white/[0.06]">
        <div className="relative flex-shrink-0 w-9 h-9 rounded-xl bg-gradient-to-br from-electric-500/20 to-purple-500/20 flex items-center justify-center border border-white/[0.08]">
          <Sparkles className="w-5 h-5 text-electric-400" />
          <div className="absolute inset-0 rounded-xl bg-electric-500/10 animate-pulse-glow" />
        </div>
        <AnimatePresence>
          {!collapsed && (
            <motion.div
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              transition={{ duration: 0.2 }}
              className="flex flex-col"
            >
              <span className="text-sm font-bold text-white tracking-tight">AIONEX</span>
              <span className="text-[10px] text-white/40 font-medium tracking-widest uppercase">AIOS</span>
            </motion.div>
          )}
        </AnimatePresence>
        <button
          onClick={onToggle}
          className="ml-auto p-1.5 rounded-lg hover:bg-white/[0.08] transition-colors"
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4 text-white/40" />
          ) : (
            <ChevronLeft className="w-4 h-4 text-white/40" />
          )}
        </button>
      </div>

      {/* Workspace Switcher */}
      <div className="px-3 py-3 border-b border-white/[0.06]">
        <button className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] transition-all duration-200 group">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center flex-shrink-0 border border-white/[0.08]">
            <Building2 className="w-3.5 h-3.5 text-blue-400" />
          </div>
          <AnimatePresence>
            {!collapsed && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex flex-col items-start flex-1 min-w-0"
              >
                <span className="text-xs font-semibold text-white truncate">AIONEX Corp</span>
                <span className="text-[10px] text-white/40">Enterprise Plan</span>
              </motion.div>
            )}
          </AnimatePresence>
          {!collapsed && <ChevronRight className="w-3.5 h-3.5 text-white/30 group-hover:text-white/60 transition-colors" />}
        </button>
      </div>

      {/* Quick Access */}
      {!collapsed && (
        <div className="px-3 py-2 border-b border-white/[0.06]">
          <div className="flex items-center gap-2 px-3 mb-2">
            <Star className="w-3 h-3 text-white/30" />
            <span className="text-[10px] font-semibold text-white/30 uppercase tracking-wider">Favorites</span>
          </div>
          <div className="space-y-0.5">
            {favorites.map((fav) => (
              <button
                key={fav}
                className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs text-white/50 hover:text-white/80 hover:bg-white/[0.04] transition-all"
              >
                <Pin className="w-3 h-3" />
                <span className="truncate">{fav}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Main Navigation */}
      <div className="flex-1 overflow-y-auto py-2 px-3 scrollbar-thin">
        <div className="space-y-0.5">
          {mainNavSections.map((section) => {
            const Icon = section.icon;
            const hasChildren = section.children && section.children.length > 0;
            const isExpanded = expandedSections.includes(section.id);
            const isSectionActive = hasChildren
              ? section.children?.some((child) => isActive(child.href))
              : isActive(section.href || "");

            return (
              <div key={section.id}>
                {hasChildren ? (
                  <>
                    <button
                      onClick={() => toggleSection(section.id)}
                      className={cn(
                        "w-full flex items-center gap-3 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200",
                        isSectionActive
                          ? "text-white bg-white/[0.08]"
                          : "text-white/50 hover:text-white/80 hover:bg-white/[0.04]"
                      )}
                    >
                      <Icon className={cn("w-[18px] h-[18px] flex-shrink-0", isSectionActive && "text-electric-400")} />
                      <AnimatePresence>
                        {!collapsed && (
                          <motion.span
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            className="flex-1 text-left"
                          >
                            {section.label}
                          </motion.span>
                        )}
                      </AnimatePresence>
                      {!collapsed && (
                        <motion.div
                          animate={{ rotate: isExpanded ? 90 : 0 }}
                          transition={{ duration: 0.2 }}
                        >
                          <ChevronRight className="w-3.5 h-3.5 text-white/30" />
                        </motion.div>
                      )}
                      {!collapsed && section.badge && (
                        <span className="flex-shrink-0 px-1.5 py-0.5 rounded-md bg-white/[0.08] text-[10px] font-semibold text-white/60">
                          {section.badge}
                        </span>
                      )}
                    </button>
                    <AnimatePresence>
                      {isExpanded && !collapsed && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                          className="overflow-hidden"
                        >
                          <div className="ml-4 pl-3 border-l border-white/[0.06] space-y-0.5 mt-0.5">
                            {section.children?.map((child) => (
                              <Link
                                key={child.id}
                                href={child.href}
                                className={cn(
                                  "flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200",
                                  isActive(child.href)
                                    ? "text-white bg-white/[0.06]"
                                    : "text-white/40 hover:text-white/70 hover:bg-white/[0.03]"
                                )}
                              >
                                <child.icon className="w-3.5 h-3.5" />
                                <span className="flex-1">{child.label}</span>
                                {child.badge && (
                                  <span className="flex-shrink-0 px-1.5 py-0.5 rounded-md bg-white/[0.06] text-[10px] font-medium text-white/50">
                                    {child.badge}
                                  </span>
                                )}
                              </Link>
                            ))}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </>
                ) : (
                  <Link
                    href={section.href || "/"}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200 relative",
                      isActive(section.href || "")
                        ? "text-white bg-white/[0.08]"
                        : "text-white/50 hover:text-white/80 hover:bg-white/[0.04]"
                    )}
                  >
                    {isActive(section.href || "") && (
                      <motion.div
                        layoutId="sidebar-active"
                        className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-electric-500"
                        style={{ boxShadow: "0 0 10px rgba(0, 212, 255, 0.5)" }}
                        transition={{ type: "spring", stiffness: 300, damping: 30 }}
                      />
                    )}
                    <Icon className={cn("w-[18px] h-[18px] flex-shrink-0", isActive(section.href || "") && "text-electric-400")} />
                    <AnimatePresence>
                      {!collapsed && (
                        <motion.span
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          className="flex-1"
                        >
                          {section.label}
                        </motion.span>
                      )}
                    </AnimatePresence>
                    {!collapsed && section.badge && (
                      <span className="flex-shrink-0 px-1.5 py-0.5 rounded-md bg-white/[0.08] text-[10px] font-semibold text-white/60">
                        {section.badge}
                      </span>
                    )}
                  </Link>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Bottom Navigation */}
      <div className="px-3 py-2 border-t border-white/[0.06]">
        {bottomNavSections.map((section) => {
          const Icon = section.icon;
          return (
            <Link
              key={section.id}
              href={section.href || "/"}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200",
                isActive(section.href || "")
                  ? "text-white bg-white/[0.08]"
                  : "text-white/50 hover:text-white/80 hover:bg-white/[0.04]"
              )}
            >
              <Icon className="w-[18px] h-[18px] flex-shrink-0" />
              <AnimatePresence>
                {!collapsed && (
                  <motion.span
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                  >
                    {section.label}
                  </motion.span>
                )}
              </AnimatePresence>
            </Link>
          );
        })}
      </div>
    </motion.aside>
  );
}
