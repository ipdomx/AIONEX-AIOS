"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  RefreshCw,
  Server,
  ShieldCheck,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type HealthSignal = {
  id: string;
  name: string;
  status: string;
  detail: string;
};

const healthIcons: Record<string, React.ElementType> = {
  database: Database,
  backend: Server,
  operations: Activity,
};

function healthy(status: string) {
  return ["healthy", "ready", "ok", "operational"].includes(
    status.toLowerCase(),
  );
}

export default function OwnerHealthPage() {
  const { items, loading, busy, message, execute } =
    useOwnerResource<HealthSignal>("health");
  const healthyCount = items.filter((item) => healthy(item.status)).length;

  function refreshHealth() {
    void execute("all", "refresh");
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
      >
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Owner System Health
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Central live health verification for the AIONEX AIOS control plane.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={refreshHealth}
            disabled={loading || busy}
            className="rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-2.5 text-sm font-medium text-white/75 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className="mr-2 inline h-4 w-4" />
            Refresh health
          </button>
          <Link href="/owner/incidents" className="btn-primary">
            Open incident command
          </Link>
        </div>
      </motion.div>

      <div className="text-xs text-electric-300">
        {loading ? "Running live health checks..." : message}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {items.map((system, index) => {
          const Icon = healthIcons[system.id] ?? ShieldCheck;
          const isHealthy = healthy(system.status);
          return (
            <motion.section
              key={system.id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.04 }}
              className="glass-card p-5"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                    <Icon className="h-5 w-5 text-electric-300" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-white">
                      {system.name}
                    </h2>
                    <p className="mt-1 text-xs text-white/40">
                      {system.detail}
                    </p>
                  </div>
                </div>
                <span
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-medium ${
                    isHealthy
                      ? "border-green-500/20 bg-green-500/10 text-green-400"
                      : "border-orange-500/20 bg-orange-500/10 text-orange-400"
                  }`}
                >
                  {isHealthy ? (
                    <CheckCircle2 className="h-3 w-3" />
                  ) : (
                    <AlertTriangle className="h-3 w-3" />
                  )}
                  {system.status}
                </span>
              </div>
            </motion.section>
          );
        })}
      </div>

      {!loading && items.length === 0 && (
        <div className="glass-card p-6 text-sm text-white/45">
          No health signals were returned by the Owner API.
        </div>
      )}

      <section className="glass-card p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">
            Live validation signals
          </h2>
          <span
            className={`text-xs ${
              healthyCount === items.length && items.length > 0
                ? "text-green-400"
                : "text-orange-300"
            }`}
          >
            {healthyCount} / {items.length} healthy
          </span>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {items.map((item) => {
            const isHealthy = healthy(item.status);
            return (
              <div
                key={item.id}
                className="flex items-center gap-2 rounded-xl border border-white/[0.05] bg-white/[0.02] px-4 py-3 text-xs text-white/60"
              >
                {isHealthy ? (
                  <CheckCircle2 className="h-4 w-4 text-green-400" />
                ) : (
                  <AlertTriangle className="h-4 w-4 text-orange-300" />
                )}
                {item.name}: {item.status}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
