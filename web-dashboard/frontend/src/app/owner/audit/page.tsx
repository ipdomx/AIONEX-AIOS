"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Filter,
  RefreshCw,
  Search,
  ShieldCheck,
  UserRound,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type AuditEvent = {
  id: string;
  actor: string;
  action: string;
  target: string;
  severity: string;
  status: string;
  timestamp: string;
};

function formatTimestamp(value: string) {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString();
}

export default function OwnerAuditPage() {
  const { items, loading, busy, message, reload } =
    useOwnerResource<AuditEvent>("audit");
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("all");

  const events = useMemo(
    () =>
      items.filter((event) => {
        const text =
          `${event.actor} ${event.action} ${event.target}`.toLowerCase();
        return (
          text.includes(query.toLowerCase()) &&
          (severity === "all" || event.severity === severity)
        );
      }),
    [items, query, severity],
  );

  const severityOptions = useMemo(
    () => ["all", ...Array.from(new Set(items.map((item) => item.severity)))],
    [items],
  );

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
      >
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <ShieldCheck className="h-3.5 w-3.5" /> Owner Audit Command
          </div>
          <h1 className="mt-3 text-3xl font-bold text-white">
            Owner Audit &amp; Accountability
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Full visibility into owner decisions, approvals, internal staff
            actions, policy changes, incidents and governance events.
          </p>
        </div>
        <button
          onClick={() => void reload()}
          disabled={loading || busy}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh audit
        </button>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          { label: "Tracked Events", value: items.length, icon: Activity },
          {
            label: "Pending Review",
            value: items.filter((item) => item.status === "pending").length,
            icon: AlertTriangle,
          },
          {
            label: "Completed",
            value: items.filter((item) => item.status === "completed").length,
            icon: CheckCircle2,
          },
        ].map((item) => {
          const Icon = item.icon;
          return (
            <div key={item.label} className="glass-card p-5">
              <div className="flex items-center justify-between">
                <Icon className="h-5 w-5 text-electric-300" />
                <span className="text-2xl font-bold text-white">
                  {item.value}
                </span>
              </div>
              <p className="mt-3 text-xs uppercase tracking-wider text-white/35">
                {item.label}
              </p>
            </div>
          );
        })}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search actor, action or target..."
              className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none"
            />
          </div>
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-white/35" />
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
              className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
            >
              {severityOptions.map((option) => (
                <option key={option} value={option} className="bg-space-800">
                  {option === "all" ? "All severity" : option}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="mt-3 text-xs text-electric-300">
          {loading ? "Loading owner audit events..." : message}
        </div>
      </div>

      <div className="space-y-3">
        {!loading && events.length === 0 && (
          <div className="glass-card p-6 text-sm text-white/45">
            No audit events match the current filters.
          </div>
        )}
        {events.map((event, index) => (
          <motion.div
            key={event.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.04 }}
            className="glass-card p-5"
          >
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-start gap-3">
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                  <UserRound className="h-4 w-4 text-electric-300" />
                </div>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-sm font-semibold text-white">
                      {event.actor}
                    </h2>
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[10px] ${
                        event.severity === "critical"
                          ? "border-red-500/20 bg-red-500/10 text-red-300"
                          : event.severity === "warning"
                            ? "border-orange-500/20 bg-orange-500/10 text-orange-300"
                            : "border-blue-500/20 bg-blue-500/10 text-blue-300"
                      }`}
                    >
                      {event.severity}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-white/55">{event.action}</p>
                  <p className="mt-1 text-[11px] text-white/30">
                    Target: {event.target}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[11px] text-white/30">
                  {formatTimestamp(event.timestamp)}
                </span>
                <span
                  className={`rounded-full border px-2.5 py-1 text-[10px] ${
                    event.status === "completed"
                      ? "border-green-500/20 bg-green-500/10 text-green-300"
                      : event.status === "failed" || event.status === "blocked"
                        ? "border-red-500/20 bg-red-500/10 text-red-300"
                        : "border-orange-500/20 bg-orange-500/10 text-orange-300"
                  }`}
                >
                  {event.status}
                </span>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
