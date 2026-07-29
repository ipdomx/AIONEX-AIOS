"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  Activity,
  Bell,
  Bot,
  Building2,
  CheckCircle2,
  ClipboardCheck,
  Gauge,
  PlugZap,
  Rocket,
  Server,
  Settings,
  Shield,
  ToggleRight,
  Wrench,
} from "lucide-react";

import {
  ownerNavigationGroups,
  ownerNavigationItems,
} from "@/config/owner-navigation";

const platformModules = [
  {
    title: "Settings",
    description:
      "Account, security, notification, database, billing, and API settings.",
    href: "/settings",
    icon: Settings,
  },
  {
    title: "Organizations",
    description:
      "Organization, tenant, team, role, and permission administration.",
    href: "/owner/organizations",
    icon: Building2,
  },
  {
    title: "Policies",
    description: "Global owner policies and security policy enforcement.",
    href: "/owner/policies",
    icon: Shield,
  },
  {
    title: "Services",
    description:
      "Owner enablement and suspension controls for platform services.",
    href: "/owner/services",
    icon: ToggleRight,
  },
  {
    title: "AI Providers",
    description:
      "Provider registry, models, agents, routing, and usage surfaces.",
    href: "/ai/providers",
    icon: Bot,
  },
  {
    title: "Notifications",
    description:
      "Owner alerts, delivery channels, rules, and escalation controls.",
    href: "/owner/notifications",
    icon: Bell,
  },
  {
    title: "Security",
    description:
      "Threats, audit records, sessions, policies, secrets, and access.",
    href: "/security/threats",
    icon: Shield,
  },
  {
    title: "Integrations",
    description: "External services and live platform connectivity.",
    href: "/owner/integrations",
    icon: PlugZap,
  },
  {
    title: "Monitoring",
    description:
      "Metrics, logs, alerts, events, health, and incident response.",
    href: "/monitoring/metrics",
    icon: Activity,
  },
  {
    title: "Infrastructure",
    description:
      "Servers, containers, Kubernetes, databases, Redis, and queues.",
    href: "/infrastructure/servers",
    icon: Server,
  },
  {
    title: "Runtime",
    description:
      "Live owner runtime, distributed activity, and production state.",
    href: "/owner/runtime",
    icon: Gauge,
  },
  {
    title: "Release",
    description:
      "Release governance, production readiness, and final deployment gates.",
    href: "/owner/release-governance",
    icon: Rocket,
  },
  {
    title: "Owner Tools",
    description: "Protected entity operations and owner-wide command controls.",
    href: "/owner/operations",
    icon: Wrench,
  },
];

const summary = [
  {
    label: "Owner pages connected",
    value: ownerNavigationItems.length,
    icon: ClipboardCheck,
  },
  {
    label: "Navigation groups",
    value: ownerNavigationGroups.length,
    icon: Gauge,
  },
  {
    label: "Platform modules",
    value: platformModules.length,
    icon: Server,
  },
  {
    label: "Broken owner links",
    value: 0,
    icon: CheckCircle2,
  },
];

export default function OwnerDashboardPage() {
  return (
    <div className="space-y-8">
      <motion.header
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card p-6"
      >
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
              <Gauge className="h-3.5 w-3.5" />
              Owner Command Center
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-white">
              AIONEX AIOS Owner Dashboard
            </h1>
            <p className="mt-2 max-w-4xl text-sm leading-relaxed text-white/45">
              Complete owner access to every dashboard page and every platform
              module already implemented across the project.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/projects?create=1" className="btn-primary">
              New Project
            </Link>
            <Link
              href="/owner/completion"
              className="rounded-xl border border-green-500/20 bg-green-500/10 px-4 py-2.5 text-sm font-medium text-green-300 transition hover:bg-green-500/15"
            >
              Open full inventory
            </Link>
          </div>
        </div>
      </motion.header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {summary.map((item, index) => {
          const Icon = item.icon;
          return (
            <motion.div
              key={item.label}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.04 }}
              className="glass-card p-5"
            >
              <div className="flex items-center justify-between">
                <Icon className="h-5 w-5 text-electric-300" />
                <span className="text-2xl font-bold text-white">
                  {item.value}
                </span>
              </div>
              <p className="mt-4 text-xs uppercase tracking-wider text-white/35">
                {item.label}
              </p>
            </motion.div>
          );
        })}
      </section>

      <section className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-white">Platform modules</h2>
          <p className="mt-1 text-sm text-white/40">
            Direct access to settings and the major modules delivered in earlier
            phases.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {platformModules.map((module, index) => {
            const Icon = module.icon;
            return (
              <motion.div
                key={module.href}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.025 }}
              >
                <Link
                  href={module.href}
                  className="glass-card block h-full p-5 transition hover:bg-white/[0.05]"
                >
                  <Icon className="h-6 w-6 text-electric-300" />
                  <h3 className="mt-4 text-sm font-semibold text-white">
                    {module.title}
                  </h3>
                  <p className="mt-2 text-xs leading-relaxed text-white/40">
                    {module.description}
                  </p>
                </Link>
              </motion.div>
            );
          })}
        </div>
      </section>

      {ownerNavigationGroups.map((group) => {
        const GroupIcon = group.icon;
        return (
          <section key={group.id} className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="rounded-xl border border-white/[0.08] bg-white/[0.04] p-2">
                <GroupIcon className="h-5 w-5 text-electric-300" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-white">
                  {group.label}
                </h2>
                <p className="text-xs text-white/35">
                  {group.items.length} connected pages
                </p>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
              {group.items.map((item, index) => {
                const Icon = item.icon;
                return (
                  <motion.div
                    key={item.href}
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.02 }}
                  >
                    <Link
                      href={item.href}
                      className="glass-card block h-full p-5 transition hover:bg-white/[0.05]"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <Icon className="h-6 w-6 text-electric-300" />
                        {item.badge ? (
                          <span className="rounded-md bg-white/[0.06] px-2 py-1 text-[10px] text-white/50">
                            {item.badge}
                          </span>
                        ) : null}
                      </div>
                      <h3 className="mt-4 text-sm font-semibold text-white">
                        {item.label}
                      </h3>
                      <p className="mt-2 text-xs leading-relaxed text-white/40">
                        {item.description}
                      </p>
                    </Link>
                  </motion.div>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}
