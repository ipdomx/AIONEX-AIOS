"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  Building2,
  CheckCircle2,
  FolderKanban,
  PauseCircle,
  PlayCircle,
  Search,
  Server,
  ShieldCheck,
  Users,
  XCircle,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type EntityType = "project" | "organization" | "service";

type Entity = {
  id: string;
  type: EntityType;
  name: string;
  status: string;
  risk: "low" | "medium" | "high" | "critical";
  owner: string;
  protected?: boolean;
  updatedAt: string;
};

type SummaryCard = {
  label: string;
  value: number;
  icon: React.ElementType;
};

const iconMap: Record<EntityType, React.ElementType> = {
  project: FolderKanban,
  organization: Building2,
  service: Server,
};

function statusStyle(status: string) {
  if (status === "active")
    return "border-green-500/20 bg-green-500/10 text-green-400";
  if (status === "paused" || status === "suspended")
    return "border-orange-500/20 bg-orange-500/10 text-orange-400";
  if (status === "warning")
    return "border-yellow-500/20 bg-yellow-500/10 text-yellow-300";
  return "border-red-500/20 bg-red-500/10 text-red-400";
}

const riskStyles: Record<Entity["risk"], string> = {
  low: "text-green-400",
  medium: "text-blue-300",
  high: "text-orange-400",
  critical: "text-red-400",
};

export default function OwnerGlobalCommandPage() {
  const { items, loading, busy, message, execute } =
    useOwnerResource<Entity>("global-command");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | EntityType>("all");

  const filtered = useMemo(
    () =>
      items.filter((entity) => {
        const matchesQuery = `${entity.name} ${entity.owner} ${entity.status}`
          .toLowerCase()
          .includes(query.toLowerCase());
        const matchesType = typeFilter === "all" || entity.type === typeFilter;
        return matchesQuery && matchesType;
      }),
    [items, query, typeFilter],
  );

  const summaryCards: SummaryCard[] = [
    {
      label: "Projects",
      value: items.filter((item) => item.type === "project").length,
      icon: FolderKanban,
    },
    {
      label: "Organizations",
      value: items.filter((item) => item.type === "organization").length,
      icon: Users,
    },
    {
      label: "Services",
      value: items.filter((item) => item.type === "service").length,
      icon: Server,
    },
    {
      label: "High risk",
      value: items.filter((item) => item.risk === "high").length,
      icon: AlertTriangle,
    },
    {
      label: "Critical",
      value: items.filter((item) => item.risk === "critical").length,
      icon: AlertTriangle,
    },
  ];

  function runGlobalAction(action: "resume" | "pause" | "validate") {
    if (
      action !== "validate" &&
      !window.confirm(
        action === "pause"
          ? "Pause active and running projects? Planning, review, completed, archived and deleted projects are preserved."
          : "Resume paused projects? All other project states are preserved.",
      )
    ) {
      return;
    }
    void execute("all", action);
  }

  function runEntityAction(entity: Entity, action: "activate" | "pause") {
    const actionLabel =
      action === "activate"
        ? "Activate"
        : entity.type === "organization"
          ? "Restrict"
          : "Pause";
    if (
      !window.confirm(
        `${actionLabel} ${entity.name}? This audited command changes live ${entity.type} state.`,
      )
    ) {
      return;
    }
    const backendAction =
      action === "pause" && entity.type === "organization" ? "offline" : action;
    void execute(entity.id, backendAction);
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <ShieldCheck className="h-3.5 w-3.5" /> Owner Global Command
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Global Command Center
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Execute owner-level controls across projects, organizations and
            platform services.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => runGlobalAction("resume")}
            disabled={loading || busy}
            className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <PlayCircle className="h-4 w-4" />
            Resume paused projects
          </button>
          <button
            onClick={() => runGlobalAction("pause")}
            disabled={loading || busy}
            className="rounded-xl border border-orange-500/20 bg-orange-500/10 px-4 py-2.5 text-sm font-medium text-orange-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <PauseCircle className="mr-2 inline h-4 w-4" />
            Pause active projects
          </button>
          <button
            onClick={() => runGlobalAction("validate")}
            disabled={loading || busy}
            className="rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-2.5 text-sm font-medium text-white/75 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <CheckCircle2 className="mr-2 inline h-4 w-4" />
            Validate
          </button>
        </div>
      </motion.div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {summaryCards.map(({ label, value, icon: Icon }) => (
          <div key={label} className="glass-card p-4">
            <Icon className="h-5 w-5 text-electric-300" />
            <div className="mt-3 text-2xl font-bold text-white">{value}</div>
            <div className="text-xs text-white/35">{label}</div>
          </div>
        ))}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full max-w-xl">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search every controlled entity..."
              className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none"
            />
          </div>
          <select
            value={typeFilter}
            onChange={(event) =>
              setTypeFilter(event.target.value as typeof typeFilter)
            }
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          >
            <option value="all" className="bg-space-800">
              All entities
            </option>
            <option value="project" className="bg-space-800">
              Projects
            </option>
            <option value="organization" className="bg-space-800">
              Organizations
            </option>
            <option value="service" className="bg-space-800">
              Services
            </option>
          </select>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-electric-300">
          <Activity className="h-3.5 w-3.5" />
          {loading ? "Loading controlled entities..." : message}
        </div>
      </div>

      <div className="space-y-3">
        {!loading && filtered.length === 0 && (
          <div className="glass-card p-6 text-sm text-white/45">
            No controlled entities match the current filters.
          </div>
        )}
        {filtered.map((entity, index) => {
          const Icon = iconMap[entity.type] ?? Server;
          return (
            <motion.div
              key={`${entity.type}-${entity.id}`}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.03 }}
              className="glass-card p-5"
            >
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex items-start gap-3">
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                    <Icon className="h-5 w-5 text-electric-300" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-white">
                      {entity.name}
                    </h2>
                    <p className="mt-1 text-xs text-white/40">
                      {entity.type} · Owner: {entity.owner}
                    </p>
                    <p
                      className={`mt-2 text-xs font-medium ${
                        riskStyles[entity.risk] ?? "text-white/45"
                      }`}
                    >
                      Risk: {entity.risk}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded-full border px-2.5 py-1 text-xs ${statusStyle(
                      entity.status,
                    )}`}
                  >
                    {entity.status}
                  </span>
                  {((entity.type === "project" && entity.status === "paused") ||
                    (entity.type === "organization" &&
                      [
                        "inactive",
                        "offline",
                        "restricted",
                        "suspended",
                      ].includes(entity.status)) ||
                    (entity.type === "service" &&
                      entity.status === "paused")) &&
                    !entity.protected && (
                      <button
                        onClick={() => runEntityAction(entity, "activate")}
                        disabled={busy}
                        className="rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Activate
                      </button>
                    )}
                  {((entity.type === "project" &&
                    ["active", "in_progress", "planning", "running"].includes(
                      entity.status,
                    )) ||
                    (entity.type === "organization" &&
                      ["active", "trial"].includes(entity.status)) ||
                    (entity.type === "service" &&
                      entity.status === "active")) &&
                    !entity.protected && (
                      <button
                        onClick={() => runEntityAction(entity, "pause")}
                        disabled={busy}
                        className="rounded-lg border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {entity.type === "organization" ? (
                          <>
                            <XCircle className="mr-1 inline h-3.5 w-3.5" />
                            Restrict
                          </>
                        ) : (
                          <>
                            <PauseCircle className="mr-1 inline h-3.5 w-3.5" />
                            Pause
                          </>
                        )}
                      </button>
                    )}
                  {entity.protected && (
                    <span className="rounded-lg border border-white/[0.08] px-3 py-2 text-xs text-white/35">
                      Protected
                    </span>
                  )}
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>

      <div className="flex justify-end">
        <Link href="/owner" className="text-xs text-electric-300">
          Back to Owner Center
        </Link>
      </div>
    </div>
  );
}
