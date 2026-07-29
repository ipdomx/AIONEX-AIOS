"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  Building2,
  CheckCircle2,
  FolderKanban,
  Gauge,
  RefreshCw,
  ShieldCheck,
  Users,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type ExecutiveMetric = {
  id: string;
  label: string;
  value: number;
  unit: string;
  trend: number | null;
  status: string;
};

const metricPresentation: Record<
  string,
  { href: string; icon: React.ElementType }
> = {
  organizations: { href: "/owner/organizations", icon: Building2 },
  projects: { href: "/owner/projects", icon: FolderKanban },
  users: { href: "/owner/staff", icon: Users },
  alerts: { href: "/owner/incidents", icon: AlertTriangle },
};

export default function OwnerExecutivePage() {
  const { items, loading, busy, message, reload } =
    useOwnerResource<ExecutiveMetric>("executive");
  const attentionItems = items.filter((item) => item.status !== "good");

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <Gauge className="h-3.5 w-3.5" />
            Owner Executive Overview
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Enterprise Command Summary
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-white/45">
            Live owner-level visibility across organizations, projects, users
            and active incidents.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => void reload()}
            disabled={loading || busy}
            className="rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-2.5 text-sm font-medium text-white/75 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className="mr-2 inline h-4 w-4" />
            Refresh
          </button>
          <Link href="/owner/approvals" className="btn-primary">
            Review pending approvals
          </Link>
        </div>
      </motion.div>

      <div className="text-xs text-electric-300">
        {loading ? "Loading executive metrics..." : message}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((item, index) => {
          const presentation = metricPresentation[item.id] ?? {
            href: "/owner",
            icon: Activity,
          };
          const Icon = presentation.icon;
          return (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.04 }}
            >
              <Link
                href={presentation.href}
                className="glass-card block p-5 transition hover:bg-white/[0.05]"
              >
                <div className="flex items-center justify-between">
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                    <Icon className="h-5 w-5 text-electric-300" />
                  </div>
                  <span className="text-2xl font-bold text-white">
                    {item.value}
                    {item.unit}
                  </span>
                </div>
                <p className="mt-4 text-xs uppercase tracking-wider text-white/35">
                  {item.label}
                </p>
              </Link>
            </motion.div>
          );
        })}
      </div>

      {!loading && items.length === 0 && (
        <div className="glass-card p-6 text-sm text-white/45">
          No executive metrics are available.
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="glass-card p-5">
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-green-400" />
            <h2 className="text-sm font-semibold text-white">
              Enterprise signals
            </h2>
          </div>
          <div className="space-y-3">
            {items.map((item) => {
              const healthy = item.status === "good";
              return (
                <div
                  key={item.id}
                  className="flex items-center justify-between rounded-xl border border-white/[0.05] bg-white/[0.02] px-4 py-3"
                >
                  <span className="text-xs text-white/55">{item.label}</span>
                  <span
                    className={`inline-flex items-center gap-1 text-xs ${
                      healthy ? "text-green-400" : "text-orange-300"
                    }`}
                  >
                    {healthy ? (
                      <CheckCircle2 className="h-3.5 w-3.5" />
                    ) : (
                      <AlertTriangle className="h-3.5 w-3.5" />
                    )}
                    {item.status}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
        <section className="glass-card p-5">
          <div className="mb-4 flex items-center gap-2">
            <Activity className="h-5 w-5 text-electric-300" />
            <h2 className="text-sm font-semibold text-white">
              Owner priorities
            </h2>
          </div>
          {attentionItems.length > 0 ? (
            <div className="space-y-3">
              {attentionItems.map((item, index) => (
                <div
                  key={item.id}
                  className="flex items-center gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] px-4 py-3"
                >
                  <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-electric-500/10 text-xs font-bold text-electric-300">
                    {index + 1}
                  </span>
                  <span className="text-xs text-white/60">
                    Review {item.label.toLowerCase()}: {item.value}
                    {item.unit}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="rounded-xl border border-white/[0.05] bg-white/[0.02] px-4 py-3 text-xs text-white/45">
              No live executive signal currently requires owner attention.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
