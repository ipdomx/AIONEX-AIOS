"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  Bell,
  Bot,
  Building2,
  Calendar,
  CheckCircle2,
  Database,
  FolderKanban,
  Gauge,
  GitPullRequest,
  Network,
  Server,
  ShieldCheck,
  Users,
  Workflow,
} from "lucide-react";

const cards = [
  { title: "Projects", value: "12", icon: FolderKanban, href: "/projects" },
  { title: "Users", value: "2,847", icon: Users, href: "/users" },
  { title: "Organizations", value: "18", icon: Building2, href: "/users/organizations" },
  { title: "AI Agents", value: "156", icon: Bot, href: "/ai/agents" },
  { title: "Workflows", value: "89", icon: Workflow, href: "/workflows" },
  { title: "Servers", value: "42", icon: Server, href: "/infrastructure/servers" },
  { title: "Databases", value: "18", icon: Database, href: "/infrastructure/databases" },
  { title: "Open Alerts", value: "3", icon: AlertTriangle, href: "/monitoring/alerts" },
  { title: "Pending Approvals", value: "7", icon: GitPullRequest, href: "/owner/approvals" },
  { title: "Meetings", value: "6", icon: Calendar, href: "/meetings" },
  { title: "Security Events", value: "14", icon: ShieldCheck, href: "/security/audit" },
  { title: "Notifications", value: "24", icon: Bell, href: "/owner/notifications" },
];

const controls = [
  { title: "Governance & Approvals", description: "Review owner-only approvals, decisions, meetings and high-risk operations.", href: "/owner/approvals", icon: GitPullRequest },
  { title: "Organization Control", description: "Manage organizations, plans, service access and governance boundaries.", href: "/users/organizations", icon: Building2 },
  { title: "People & Roles", description: "Control users, teams, roles, permissions and staff visibility.", href: "/users", icon: Users },
  { title: "AI Workforce", description: "Manage providers, agents, models, usage and owner-level execution controls.", href: "/ai/agents", icon: Bot },
  { title: "Infrastructure", description: "Operate servers, containers, databases, Kubernetes, queues and health.", href: "/infrastructure/servers", icon: Network },
  { title: "Monitoring & Incidents", description: "Inspect alerts, logs, events, metrics and incident response status.", href: "/monitoring/alerts", icon: Activity },
  { title: "Security Center", description: "Review threats, policies, audit trail and active sessions.", href: "/security/threats", icon: ShieldCheck },
  { title: "Owner Notifications", description: "View project, user, staff, approval, incident and completion notifications.", href: "/owner/notifications", icon: Bell },
];

export default function OwnerDashboardPage() {
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <Gauge className="h-3.5 w-3.5" /> Owner Command Center
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">AIONEX AIOS Owner Dashboard</h1>
          <p className="mt-2 max-w-3xl text-sm text-white/45">Unified owner visibility across projects, users, internal staff, approvals, infrastructure, AI operations, incidents, notifications and governance.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/projects?create=1" className="btn-primary">New Project</Link>
          <Link href="/owner/approvals" className="rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-2.5 text-sm font-medium text-white/75 transition hover:bg-white/[0.08]">Review Approvals</Link>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card, index) => {
          const Icon = card.icon;
          return (
            <motion.div key={card.title} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }}>
              <Link href={card.href} className="glass-card block p-5 transition hover:bg-white/[0.05]">
                <div className="flex items-center justify-between">
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><Icon className="h-5 w-5 text-electric-300" /></div>
                  <span className="text-2xl font-bold text-white">{card.value}</span>
                </div>
                <p className="mt-4 text-xs font-medium uppercase tracking-wider text-white/35">{card.title}</p>
              </Link>
            </motion.div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-4">
        {controls.map((item, index) => {
          const Icon = item.icon;
          return (
            <motion.div key={item.title} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 + index * 0.04 }}>
              <Link href={item.href} className="glass-card block h-full p-5 transition hover:bg-white/[0.05]">
                <Icon className="h-6 w-6 text-electric-300" />
                <h2 className="mt-4 text-sm font-semibold text-white">{item.title}</h2>
                <p className="mt-2 text-xs leading-relaxed text-white/40">{item.description}</p>
              </Link>
            </motion.div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section className="glass-card p-5 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between"><h2 className="text-sm font-semibold text-white">Owner Activity Stream</h2><Link href="/monitoring/events" className="text-xs text-electric-300">View all</Link></div>
          <div className="space-y-3">
            {["Project release approved by owner", "Infrastructure health validation completed", "New organization access request received", "Security policy review completed", "AI provider cost threshold updated"].map((item, index) => (
              <div key={item} className="flex items-center gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] px-4 py-3">
                {index < 2 ? <CheckCircle2 className="h-4 w-4 text-green-400" /> : <Activity className="h-4 w-4 text-electric-300" />}
                <span className="flex-1 text-xs text-white/65">{item}</span><span className="text-[10px] text-white/25">Recently</span>
              </div>
            ))}
          </div>
        </section>
        <section className="glass-card p-5">
          <div className="mb-4 flex items-center justify-between"><h2 className="text-sm font-semibold text-white">System Readiness</h2><span className="text-xs text-green-400">Operational</span></div>
          <div className="space-y-4">
            {["Authentication", "Database", "API Gateway", "Frontend", "Background Workers", "Notifications"].map((name) => (
              <div key={name} className="flex items-center justify-between"><span className="text-xs text-white/45">{name}</span><span className="inline-flex items-center gap-1 text-xs text-green-400"><span className="h-1.5 w-1.5 rounded-full bg-green-400" />Ready</span></div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
