"use client";

import { useCallback, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BarChart3,
  Bell,
  BookOpen,
  Bot,
  Brain,
  Briefcase,
  Building2,
  Calendar,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Clock,
  Cpu,
  Database,
  FileText,
  FolderOpen,
  Globe,
  Layers,
  LayoutDashboard,
  Lock,
  Pin,
  Server,
  Settings,
  Shield,
  Sparkles,
  Star,
  Terminal,
  Users,
  Workflow,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import {
  ownerNavigationGroups,
  ownerRootNavigationItem,
} from "@/config/owner-navigation";
import { useAuth } from "@/components/providers/AuthProvider";
import { isOwnerRole } from "@/config/owner-access";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface SidebarProps {
  collapsed: boolean;
  mobile: boolean;
  mobileOpen: boolean;
  onNavigate: () => void;
  onToggle: () => void;
}

interface NavChild {
  id: string;
  label: string;
  icon: LucideIcon;
  href: string;
  badge?: number;
}

interface NavSection {
  id: string;
  label: string;
  icon: LucideIcon;
  href?: string;
  badge?: number;
  children?: NavChild[];
}

const mainNavSections: NavSection[] = [
  {
    id: ownerRootNavigationItem.id,
    label: ownerRootNavigationItem.label,
    icon: ownerRootNavigationItem.icon,
    href: ownerRootNavigationItem.href,
  },
  { id: "overview", label: "Overview", icon: LayoutDashboard, href: "/" },
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
      {
        id: "ai-providers",
        label: "Providers",
        icon: Zap,
        href: "/ai/providers",
      },
      {
        id: "ai-agents",
        label: "Agents",
        icon: Bot,
        href: "/ai/agents",
        badge: 8,
      },
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
  { id: "knowledge", label: "Knowledge", icon: BookOpen, href: "/knowledge" },
  {
    id: "infrastructure",
    label: "Infrastructure",
    icon: Server,
    children: [
      {
        id: "infra-servers",
        label: "Servers",
        icon: Cpu,
        href: "/infrastructure/servers",
        badge: 6,
      },
      {
        id: "infra-containers",
        label: "Containers",
        icon: Layers,
        href: "/infrastructure/containers",
      },
      {
        id: "infra-kubernetes",
        label: "Kubernetes",
        icon: Globe,
        href: "/infrastructure/kubernetes",
      },
      {
        id: "infra-databases",
        label: "Databases",
        icon: Database,
        href: "/infrastructure/databases",
      },
      {
        id: "infra-redis",
        label: "Redis",
        icon: Zap,
        href: "/infrastructure/redis",
      },
      {
        id: "infra-queues",
        label: "Queues",
        icon: Terminal,
        href: "/infrastructure/queues",
      },
    ],
  },
  {
    id: "monitoring",
    label: "Monitoring",
    icon: Activity,
    children: [
      {
        id: "mon-metrics",
        label: "Metrics",
        icon: BarChart3,
        href: "/monitoring/metrics",
      },
      {
        id: "mon-logs",
        label: "Logs",
        icon: FileText,
        href: "/monitoring/logs",
      },
      {
        id: "mon-alerts",
        label: "Alerts",
        icon: Bell,
        href: "/monitoring/alerts",
        badge: 3,
      },
      {
        id: "mon-events",
        label: "Events",
        icon: Clock,
        href: "/monitoring/events",
      },
    ],
  },
  {
    id: "security",
    label: "Security",
    icon: Shield,
    children: [
      {
        id: "sec-threats",
        label: "Threat Center",
        icon: Lock,
        href: "/security/threats",
      },
      {
        id: "sec-audit",
        label: "Audit",
        icon: FileText,
        href: "/security/audit",
      },
      {
        id: "sec-sessions",
        label: "Sessions",
        icon: Globe,
        href: "/security/sessions",
      },
      {
        id: "sec-policies",
        label: "Policies",
        icon: Shield,
        href: "/security/policies",
      },
    ],
  },
  {
    id: "users",
    label: "Users",
    icon: Users,
    children: [
      { id: "users-list", label: "All Users", icon: Users, href: "/users" },
      {
        id: "users-orgs",
        label: "Organizations",
        icon: Building2,
        href: "/users/organizations",
      },
      {
        id: "users-teams",
        label: "Teams",
        icon: Briefcase,
        href: "/users/teams",
      },
      { id: "users-roles", label: "Roles", icon: Lock, href: "/users/roles" },
      {
        id: "users-permissions",
        label: "Permissions",
        icon: Shield,
        href: "/users/permissions",
      },
    ],
  },
  ...ownerNavigationGroups.map((group) => ({
    id: group.id,
    label: group.label,
    icon: group.icon,
    children: group.items.map(({ id, label, icon, href, badge }) => ({
      id,
      label,
      icon,
      href,
      badge,
    })),
  })),
  { id: "tasks", label: "Tasks", icon: CheckSquare, href: "/tasks", badge: 15 },
  { id: "meetings", label: "Meetings", icon: Calendar, href: "/meetings" },
  { id: "reports", label: "Reports", icon: BarChart3, href: "/reports" },
];

const bottomNavSections: NavSection[] = [
  { id: "settings", label: "Settings", icon: Settings, href: "/settings" },
];

export default function Sidebar({
  collapsed,
  mobile,
  mobileOpen,
  onNavigate,
  onToggle,
}: SidebarProps) {
  const pathname = usePathname();
  const { user } = useAuth();
  const canAccessOwner = isOwnerRole(user?.role);
  const [expandedSections, setExpandedSections] = useState<string[]>([
    "ai",
    "infrastructure",
    "owner-command",
  ]);
  const favorites = [
    {
      id: "owner-runtime",
      label: "Live Ownership Data",
      href: "/owner/runtime",
    },
    {
      id: "owner-global-command",
      label: "Global Command",
      href: "/owner/global-command",
    },
    {
      id: "owner-integrations",
      label: "Integrations",
      href: "/owner/integrations",
    },
  ];

  const toggleSection = useCallback((sectionId: string) => {
    setExpandedSections((current) =>
      current.includes(sectionId)
        ? current.filter((id) => id !== sectionId)
        : [...current, sectionId],
    );
  }, []);

  const isActive = useCallback(
    (href: string) => {
      if (href === "/") return pathname === "/";
      if (href === "/owner") return pathname === "/owner";
      return pathname === href || pathname.startsWith(`${href}/`);
    },
    [pathname],
  );

  const renderBadge = (badge?: number) =>
    !collapsed && badge ? (
      <span className="flex-shrink-0 rounded-md bg-white/[0.08] px-1.5 py-0.5 text-[10px] font-semibold text-white/60">
        {badge}
      </span>
    ) : null;

  const renderSection = (section: NavSection) => {
    const SectionIcon = section.icon;
    const hasChildren = Boolean(section.children?.length);
    const expanded = expandedSections.includes(section.id);
    const active = hasChildren
      ? (section.children?.some((child) => isActive(child.href)) ?? false)
      : isActive(section.href ?? "/");

    if (hasChildren) {
      return (
        <div key={section.id}>
          <button
            type="button"
            onClick={() => {
              if (collapsed) onToggle();
              if (!expanded) toggleSection(section.id);
              else if (!collapsed) toggleSection(section.id);
            }}
            className={cn(
              "flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all",
              active
                ? "bg-white/[0.08] text-white"
                : "text-white/50 hover:bg-white/[0.04] hover:text-white/80",
            )}
          >
            <SectionIcon
              className={cn(
                "h-[18px] w-[18px] flex-shrink-0",
                active && "text-electric-400",
              )}
            />
            {!collapsed && (
              <span className="flex-1 text-left">{section.label}</span>
            )}
            {!collapsed && (
              <ChevronRight
                className={cn(
                  "h-3.5 w-3.5 text-white/30 transition-transform",
                  expanded && "rotate-90",
                )}
              />
            )}
            {renderBadge(section.badge)}
          </button>
          <AnimatePresence>
            {expanded && !collapsed && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="ml-4 mt-0.5 space-y-0.5 border-l border-white/[0.06] pl-3">
                  {section.children?.map((child) => {
                    const ChildIcon = child.icon;
                    return (
                      <Link
                        key={child.id}
                        href={child.href}
                        onClick={onNavigate}
                        className={cn(
                          "flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
                          isActive(child.href)
                            ? "bg-white/[0.06] text-white"
                            : "text-white/40 hover:bg-white/[0.03] hover:text-white/70",
                        )}
                      >
                        <ChildIcon className="h-3.5 w-3.5" />
                        <span className="flex-1">{child.label}</span>
                        {child.badge ? (
                          <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-white/50">
                            {child.badge}
                          </span>
                        ) : null}
                      </Link>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      );
    }

    const href = section.href ?? "/";
    return (
      <Link
        key={section.id}
        href={href}
        onClick={onNavigate}
        className={cn(
          "relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all",
          isActive(href)
            ? "bg-white/[0.08] text-white"
            : "text-white/50 hover:bg-white/[0.04] hover:text-white/80",
        )}
      >
        <SectionIcon
          className={cn(
            "h-[18px] w-[18px] flex-shrink-0",
            isActive(href) && "text-electric-400",
          )}
        />
        {!collapsed && <span className="flex-1">{section.label}</span>}
        {renderBadge(section.badge)}
      </Link>
    );
  };

  const visibleMainNavSections = canAccessOwner
    ? mainNavSections
    : mainNavSections.filter(
        (section) => section.id !== "owner" && !section.id.startsWith("owner-"),
      );

  return (
    <motion.aside
      initial={false}
      animate={{
        width: mobile ? 280 : collapsed ? 72 : 280,
        x: mobile && !mobileOpen ? -280 : 0,
      }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="glass-strong fixed left-0 top-0 z-50 flex h-screen flex-col border-r border-white/[0.06]"
    >
      <div className="flex h-16 items-center gap-3 border-b border-white/[0.06] px-4">
        <div className="relative flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.04]">
          <Sparkles className="h-5 w-5 text-electric-300" />
        </div>
        {!collapsed && (
          <div>
            <div className="text-sm font-semibold text-white">AIONEX AIOS</div>
            <div className="text-[10px] text-white/35">Owner Control</div>
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-4">
        {!collapsed && (
          <div className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/25">
            Navigation
          </div>
        )}
        <div className="space-y-1">
          {visibleMainNavSections.map(renderSection)}
        </div>
        {!collapsed && canAccessOwner && (
          <div className="mt-5 border-t border-white/[0.06] pt-4">
            <div className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/25">
              Favorites
            </div>
            {favorites.map((favorite) => (
              <Link
                key={favorite.id}
                href={favorite.href}
                onClick={onNavigate}
                className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-white/45 hover:bg-white/[0.04] hover:text-white/75"
              >
                <Star className="h-3.5 w-3.5" />
                {favorite.label}
              </Link>
            ))}
          </div>
        )}
      </div>
      <div className="border-t border-white/[0.06] p-3">
        <div className="mb-2 space-y-1">
          {bottomNavSections.map(renderSection)}
        </div>
        <button
          onClick={onToggle}
          className="flex w-full items-center justify-center rounded-xl border border-white/[0.06] bg-white/[0.03] p-2 text-white/40 hover:bg-white/[0.06] hover:text-white/70"
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </button>
      </div>
    </motion.aside>
  );
}
