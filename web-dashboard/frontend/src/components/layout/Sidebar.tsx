"use client";

import { useCallback, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  AlertTriangle,
  ArchiveRestore,
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
  Coins,
  Cpu,
  Database,
  FileText,
  FolderOpen,
  Gauge,
  Gavel,
  GitPullRequest,
  Globe,
  Layers,
  LayoutDashboard,
  Lock,
  MessageCircle,
  Pin,
  Server,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  Star,
  Terminal,
  ToggleRight,
  UserCog,
  Users,
  Workflow,
  Zap,
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
  { id: "owner", label: "Owner Center", icon: Gauge, href: "/owner" },
  { id: "overview", label: "Overview", icon: LayoutDashboard, href: "/" },
  { id: "projects", label: "Projects", icon: FolderOpen, href: "/projects", badge: 12 },
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
  { id: "workflows", label: "Workflows", icon: Workflow, href: "/workflows", badge: 24 },
  { id: "knowledge", label: "Knowledge", icon: BookOpen, href: "/knowledge" },
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
    id: "owner-governance",
    label: "Owner Governance",
    icon: GitPullRequest,
    children: [
      { id: "owner-approvals", label: "Approvals", icon: GitPullRequest, href: "/owner/approvals", badge: 7 },
      { id: "owner-notifications", label: "Notifications", icon: Bell, href: "/owner/notifications", badge: 24 },
      { id: "owner-services", label: "Service Control", icon: ToggleRight, href: "/owner/services" },
      { id: "owner-incidents", label: "Incidents", icon: AlertTriangle, href: "/owner/incidents", badge: 3 },
      { id: "owner-audit", label: "Owner Audit", icon: ShieldCheck, href: "/owner/audit" },
      { id: "owner-costs", label: "Cost Governance", icon: Coins, href: "/owner/costs" },
      { id: "owner-staff", label: "Staff Oversight", icon: UserCog, href: "/owner/staff" },
      { id: "owner-councils", label: "Councils & Ministries", icon: Gavel, href: "/owner/governance" },
      { id: "owner-communications", label: "Communications", icon: MessageCircle, href: "/owner/communications" },
      { id: "owner-recovery", label: "Recovery Center", icon: ArchiveRestore, href: "/owner/recovery" },
    ],
  },
  { id: "tasks", label: "Tasks", icon: CheckSquare, href: "/tasks", badge: 15 },
  { id: "meetings", label: "Meetings", icon: Calendar, href: "/meetings" },
  { id: "reports", label: "Reports", icon: BarChart3, href: "/reports" },
];

const bottomNavSections: NavSection[] = [
  { id: "settings", label: "Settings", icon: Settings, href: "/settings" },
];

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();
  const [expandedSections, setExpandedSections] = useState<string[]>(["ai", "infrastructure", "owner-governance"]);
  const favorites = [
    { id: "owner-communications", label: "Communications", href: "/owner/communications" },
    { id: "owner-recovery", label: "Recovery Center", href: "/owner/recovery" },
    { id: "owner-incidents", label: "Incidents", href: "/owner/incidents" },
  ];

  const toggleSection = useCallback((sectionId: string) => {
    setExpandedSections((current) =>
      current.includes(sectionId)
        ? current.filter((id) => id !== sectionId)
        : [...current, sectionId],
    );
  }, []);

  const isActive = useCallback(
    (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href)),
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
      ? section.children?.some((child) => isActive(child.href)) ?? false
      : isActive(section.href ?? "/");

    if (hasChildren) {
      return (
        <div key={section.id}>
          <button onClick={() => toggleSection(section.id)} className={cn("flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all", active ? "bg-white/[0.08] text-white" : "text-white/50 hover:bg-white/[0.04] hover:text-white/80")}>
            <SectionIcon className={cn("h-[18px] w-[18px] flex-shrink-0", active && "text-electric-400")} />
            {!collapsed && <span className="flex-1 text-left">{section.label}</span>}
            {!collapsed && <ChevronRight className={cn("h-3.5 w-3.5 text-white/30 transition-transform", expanded && "rotate-90")} />}
            {renderBadge(section.badge)}
          </button>
          <AnimatePresence>
            {expanded && !collapsed && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                <div className="ml-4 mt-0.5 space-y-0.5 border-l border-white/[0.06] pl-3">
                  {section.children?.map((child) => {
                    const ChildIcon = child.icon;
                    return (
                      <Link key={child.id} href={child.href} className={cn("flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all", isActive(child.href) ? "bg-white/[0.06] text-white" : "text-white/40 hover:bg-white/[0.03] hover:text-white/70")}>
                        <ChildIcon className="h-3.5 w-3.5" />
                        <span className="flex-1">{child.label}</span>
                        {child.badge ? <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-white/50">{child.badge}</span> : null}
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
      <Link key={section.id} href={href} className={cn("relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all", isActive(href) ? "bg-white/[0.08] text-white" : "text-white/50 hover:bg-white/[0.04] hover:text-white/80")}>
        <SectionIcon className={cn("h-[18px] w-[18px] flex-shrink-0", isActive(href) && "text-electric-400")} />
        {!collapsed && <span className="flex-1">{section.label}</span>}
        {renderBadge(section.badge)}
      </Link>
    );
  };

  return (
    <motion.aside initial={false} animate={{ width: collapsed ? 72 : 280 }} transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }} className="glass-strong fixed left-0 top-0 z-50 flex h-screen flex-col border-r border-white/[0.06]">
      <div className="flex h-16 items-center gap-3 border-b border-white/[0.06] px-4">
        <div className="relative flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border border-white/[0.08] bg-gradient-to-br from-electric-500/20 to-purple-500/20"><Sparkles className="h-5 w-5 text-electric-400" /></div>
        <AnimatePresence>{!collapsed && <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col"><span className="text-sm font-bold tracking-tight text-white">AIONEX</span><span className="text-[10px] font-medium uppercase tracking-widest text-white/40">AIOS</span></motion.div>}</AnimatePresence>
        <button onClick={onToggle} className="ml-auto rounded-lg p-1.5 transition-colors hover:bg-white/[0.08]" aria-label="Toggle sidebar">{collapsed ? <ChevronRight className="h-4 w-4 text-white/40" /> : <ChevronLeft className="h-4 w-4 text-white/40" />}</button>
      </div>
      <div className="border-b border-white/[0.06] px-3 py-3"><Link href="/owner" className="flex w-full items-center gap-2.5 rounded-xl border border-white/[0.06] bg-white/[0.03] px-3 py-2.5 transition-all hover:bg-white/[0.06]"><div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg border border-white/[0.08] bg-gradient-to-br from-blue-500/20 to-purple-500/20"><Building2 className="h-3.5 w-3.5 text-blue-400" /></div>{!collapsed && <div className="flex min-w-0 flex-1 flex-col items-start"><span className="truncate text-xs font-semibold text-white">AIONEX Corp</span><span className="text-[10px] text-white/40">Owner · Enterprise Plan</span></div>}</Link></div>
      {!collapsed && <div className="border-b border-white/[0.06] px-3 py-2"><div className="mb-2 flex items-center gap-2 px-3"><Star className="h-3 w-3 text-white/30" /><span className="text-[10px] font-semibold uppercase tracking-wider text-white/30">Favorites</span></div>{favorites.map((favorite) => <Link key={favorite.id} href={favorite.href} className="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-xs text-white/50 transition-all hover:bg-white/[0.04] hover:text-white/80"><Pin className="h-3 w-3" /><span className="truncate">{favorite.label}</span></Link>)}</div>}
      <div className="scrollbar-thin flex-1 overflow-y-auto px-3 py-2"><div className="space-y-0.5">{mainNavSections.map(renderSection)}</div></div>
      <div className="border-t border-white/[0.06] px-3 py-2"><div className="space-y-0.5">{bottomNavSections.map(renderSection)}</div></div>
    </motion.aside>
  );
}
