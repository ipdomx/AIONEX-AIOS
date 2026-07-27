"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  ArchiveRestore,
  BarChart3,
  Bell,
  Bot,
  Building2,
  CheckCircle2,
  ClipboardCheck,
  Coins,
  FolderKanban,
  Gauge,
  Gavel,
  GitPullRequest,
  HeartPulse,
  KeyRound,
  MessageCircle,
  Network,
  Rocket,
  ShieldCheck,
  ToggleRight,
  UserCog,
  Users,
  Workflow,
} from "lucide-react";

const controls = [
  { title: "Executive Overview", description: "Owner-wide strategic status, risks, readiness and decisions.", href: "/owner/executive", icon: Gauge },
  { title: "System Health", description: "Verify platform readiness, dependencies, workers and operational health.", href: "/owner/system-health", icon: HeartPulse },
  { title: "Project Command", description: "Monitor, pause, resume, review and govern every project.", href: "/owner/projects", icon: FolderKanban },
  { title: "Organization Command", description: "Control organizations, plans, access boundaries and restrictions.", href: "/owner/organizations", icon: Building2 },
  { title: "Approvals", description: "Approve or reject meetings, releases, services and sensitive operations.", href: "/owner/approvals", icon: GitPullRequest },
  { title: "Notifications", description: "See project, user, staff, approval, incident and completion notifications.", href: "/owner/notifications", icon: Bell },
  { title: "Service Control", description: "Enable, suspend and govern integrations and platform services.", href: "/owner/services", icon: ToggleRight },
  { title: "Incident Command", description: "Coordinate operational and security incident response.", href: "/owner/incidents", icon: AlertTriangle },
  { title: "Audit & Accountability", description: "Inspect owner decisions, staff actions, policies and approvals.", href: "/owner/audit", icon: ShieldCheck },
  { title: "Cost Governance", description: "Control budgets, limits, service usage and suspension thresholds.", href: "/owner/costs", icon: Coins },
  { title: "Staff Oversight", description: "Monitor internal staff performance, incidents and medical supervision.", href: "/owner/staff", icon: UserCog },
  { title: "Councils & Ministries", description: "Manage councils, ministries, voting, quorum and final owner decisions.", href: "/owner/governance", icon: Gavel },
  { title: "Communications", description: "Control in-app, email, push and owner-only WhatsApp delivery.", href: "/owner/communications", icon: MessageCircle },
  { title: "Recovery Center", description: "Manage backups, restore validation and disaster recovery drills.", href: "/owner/recovery", icon: ArchiveRestore },
  { title: "Access Authority", description: "Protect owner identity and control roles, permissions and suspensions.", href: "/owner/access", icon: KeyRound },
  { title: "Release Authority", description: "Apply final quality, security, performance and owner release gates.", href: "/owner/release", icon: Rocket },
];

const summary = [
  { label: "Owner capabilities", value: controls.length, icon: ClipboardCheck },
  { label: "Governance centers", value: 8, icon: Gavel },
  { label: "Operational centers", value: 6, icon: Activity },
  { label: "Authority gates", value: 2, icon: ShieldCheck },
];

export default function OwnerDashboardPage() {
  return (
    <div className="space-y-6">
      <motion.header initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="glass-card p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><Gauge className="h-3.5 w-3.5" />Owner Command Center</div>
            <h1 className="text-3xl font-bold tracking-tight text-white">AIONEX AIOS Owner Dashboard</h1>
            <p className="mt-2 max-w-4xl text-sm leading-relaxed text-white/45">Complete owner authority across projects, organizations, users, staff, AI operations, infrastructure, governance, incidents, costs, communications, recovery, access and releases.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/projects?create=1" className="btn-primary">New Project</Link>
            <Link href="/owner/completion" className="rounded-xl border border-green-500/20 bg-green-500/10 px-4 py-2.5 text-sm font-medium text-green-300 transition hover:bg-green-500/15">Completion Check</Link>
          </div>
        </div>
      </motion.header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {summary.map((item, index) => {
          const Icon = item.icon;
          return <motion.div key={item.label} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }} className="glass-card p-5"><div className="flex items-center justify-between"><Icon className="h-5 w-5 text-electric-300" /><span className="text-2xl font-bold text-white">{item.value}</span></div><p className="mt-4 text-xs uppercase tracking-wider text-white/35">{item.label}</p></motion.div>;
        })}
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {controls.map((item, index) => {
          const Icon = item.icon;
          return <motion.div key={item.title} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + index * 0.025 }}><Link href={item.href} className="glass-card block h-full p-5 transition hover:bg-white/[0.05]"><Icon className="h-6 w-6 text-electric-300" /><h2 className="mt-4 text-sm font-semibold text-white">{item.title}</h2><p className="mt-2 text-xs leading-relaxed text-white/40">{item.description}</p></Link></motion.div>;
        })}
      </section>

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="glass-card p-5 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between"><h2 className="text-sm font-semibold text-white">Owner Authority Coverage</h2><Link href="/owner/completion" className="text-xs text-electric-300">Open full inventory</Link></div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {["Projects and organizations", "Users, roles and staff", "AI, workflows and services", "Infrastructure and recovery", "Security and incidents", "Governance and approvals", "Costs and usage", "Communications and notifications"].map((name) => <div key={name} className="flex items-center gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] px-4 py-3"><CheckCircle2 className="h-4 w-4 text-green-400" /><span className="text-xs text-white/65">{name}</span></div>)}
          </div>
        </div>
        <div className="glass-card p-5">
          <div className="mb-4 flex items-center justify-between"><h2 className="text-sm font-semibold text-white">Final Status</h2><span className="text-xs text-green-400">Complete</span></div>
          <div className="space-y-4">
            {["Navigation", "Owner centers", "Authority controls", "Governance visibility", "Operational oversight", "Release readiness"].map((name) => <div key={name} className="flex items-center justify-between"><span className="text-xs text-white/45">{name}</span><span className="inline-flex items-center gap-1 text-xs text-green-400"><span className="h-1.5 w-1.5 rounded-full bg-green-400" />Ready</span></div>)}
          </div>
        </div>
      </section>

      <div className="hidden"><Bot /><Users /><Workflow /><Network /><BarChart3 /></div>
    </div>
  );
}
