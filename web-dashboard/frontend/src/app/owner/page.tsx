"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { CheckCircle2, Gauge, Gavel, ShieldCheck } from "lucide-react";

import {
  ownerNavigationItems,
  ownerNavigationSections,
} from "@/config/owner-navigation";

const requestedCoverage = [
  { label: "Settings", href: "/settings" },
  { label: "Organizations", href: "/owner/organizations" },
  { label: "Policies", href: "/owner/policies" },
  { label: "Services", href: "/owner/services" },
  { label: "AI Providers", href: "/ai/providers" },
  { label: "Notifications", href: "/owner/notifications" },
  { label: "Security", href: "/owner/security-integration" },
  { label: "Integrations", href: "/owner/integrations" },
  { label: "Monitoring", href: "/owner/realtime" },
  { label: "Runtime", href: "/owner/runtime" },
  { label: "Release", href: "/owner/release-governance" },
  { label: "Owner Tools", href: "/owner/global-command" },
];

export default function OwnerDashboardPage() {
  return (
    <div className="space-y-6">
      <motion.header
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card p-6"
      >
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
              <Gauge className="h-3.5 w-3.5" />
              Super Owner Command Center
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-white">
              AIONEX AIOS Owner Dashboard
            </h1>
            <p className="mt-2 max-w-4xl text-sm leading-relaxed text-white/45">
              One discoverable control plane for every Owner page already
              present in the platform.
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
              Completion Inventory
            </Link>
          </div>
        </div>
      </motion.header>

      <section className="rounded-xl border border-electric-500/15 bg-electric-500/5 px-4 py-3 text-xs leading-relaxed text-electric-200/80">
        Every existing Owner page is now reachable. Runtime clients no longer
        substitute sample success data when a backend contract is absent; those
        pages report the missing contract explicitly.
      </section>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="glass-card p-5">
          <Gauge className="h-5 w-5 text-electric-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {ownerNavigationItems.length}
          </div>
          <div className="mt-1 text-xs text-white/40">
            Registered Owner pages
          </div>
        </div>
        <div className="glass-card p-5">
          <Gavel className="h-5 w-5 text-electric-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {ownerNavigationSections.length}
          </div>
          <div className="mt-1 text-xs text-white/40">Navigation groups</div>
        </div>
        <div className="glass-card p-5">
          <ShieldCheck className="h-5 w-5 text-electric-300" />
          <div className="mt-4 text-3xl font-bold text-white">Super Owner</div>
          <div className="mt-1 text-xs text-white/40">Required global role</div>
        </div>
        <div className="glass-card p-5">
          <CheckCircle2 className="h-5 w-5 text-green-300" />
          <div className="mt-4 text-3xl font-bold text-white">
            {requestedCoverage.length}
          </div>
          <div className="mt-1 text-xs text-white/40">
            Core platform areas linked
          </div>
        </div>
      </section>

      {ownerNavigationSections.map((section) => {
        const SectionIcon = section.icon;
        return (
          <section key={section.id} className="space-y-3">
            <div className="flex items-center gap-2">
              <SectionIcon className="h-4 w-4 text-electric-300" />
              <h2 className="text-sm font-semibold text-white">
                {section.label}
              </h2>
              <span className="text-xs text-white/30">
                {section.items.length} pages
              </span>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {section.items.map((item, index) => {
                const Icon = item.icon;
                return (
                  <motion.div
                    key={item.id}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.015 }}
                  >
                    <Link
                      href={item.href}
                      className="glass-card block h-full p-5 transition hover:bg-white/[0.05]"
                    >
                      <Icon className="h-5 w-5 text-electric-300" />
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

      <section className="glass-card p-5">
        <h2 className="text-sm font-semibold text-white">
          Core platform access
        </h2>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
          {requestedCoverage.map((item) => (
            <Link
              key={item.label}
              href={item.href}
              className="flex items-center gap-2 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-3 text-xs text-white/60 transition hover:bg-white/[0.05] hover:text-white"
            >
              <CheckCircle2 className="h-3.5 w-3.5 text-green-400" />
              {item.label}
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
