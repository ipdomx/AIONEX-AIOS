"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  Cloud,
  Database,
  GitBranch,
  Globe2,
  PlugZap,
  Search,
  Server,
  ShieldCheck,
  ToggleLeft,
  ToggleRight,
  Wrench,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";
import { GrowthSocialPilotConsole } from "@/components/owner/GrowthSocialPilotConsole";
import { GrowthPaidCampaignApprovalConsole } from "@/components/owner/GrowthPaidCampaignApprovalConsole";

type Integration = {
  id: string;
  name: string;
  category: string;
  provider: string;
  status: string;
  enabled: boolean;
  configured: boolean;
  protected: boolean;
  endpoint: string;
  lastCheck: string;
};

type SummaryCard = {
  label: string;
  value: number;
  icon: React.ElementType;
};

const statusClass = (status: string) =>
  status === "connected" || status === "active" || status === "configured"
    ? "border-green-500/20 bg-green-500/10 text-green-400"
    : status === "degraded"
      ? "border-orange-500/20 bg-orange-500/10 text-orange-300"
      : status === "pending"
        ? "border-blue-500/20 bg-blue-500/10 text-blue-300"
        : "border-white/10 bg-white/[0.03] text-white/35";

const icons: Record<string, React.ElementType> = {
  cloud: Cloud,
  source: GitBranch,
  data: Database,
  database: Database,
  security: ShieldCheck,
  communication: Globe2,
  ai: Server,
  runtime: Server,
};

export default function OwnerIntegrationsPage() {
  const { items, loading, busy, message, execute } =
    useOwnerResource<Integration>("integrations");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");

  const visible = useMemo(
    () =>
      items.filter((item) => {
        const matchesQuery =
          item.name.toLowerCase().includes(query.toLowerCase()) ||
          item.provider.toLowerCase().includes(query.toLowerCase());
        const matchesCategory =
          category === "all" || item.category === category;
        return matchesQuery && matchesCategory;
      }),
    [items, query, category],
  );

  const summaryCards: SummaryCard[] = [
    {
      label: "Connected",
      value: items.filter((item) => item.status === "connected").length,
      icon: PlugZap,
    },
    {
      label: "Degraded",
      value: items.filter((item) => item.status === "degraded").length,
      icon: Activity,
    },
    {
      label: "Disabled",
      value: items.filter((item) => !item.enabled).length,
      icon: ToggleLeft,
    },
    {
      label: "Configured",
      value: items.filter((item) => item.configured).length,
      icon: Wrench,
    },
  ];

  function toggleIntegration(item: Integration) {
    if (
      item.enabled &&
      !window.confirm(`Disable ${item.name} in the Owner integration registry?`)
    ) {
      return;
    }
    void execute(item.id, "toggle");
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
            <PlugZap className="h-3.5 w-3.5" /> Owner Integration Registry
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            External Services & Providers
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Track deployment configuration and Owner enablement intent for AI,
            source, cloud, data, security and communication providers. Live
            probes are shown only where the backend supports them.
          </p>
        </div>
        <div className="rounded-xl border border-green-500/20 bg-green-500/10 px-4 py-2.5 text-sm text-green-300">
          {items.filter((item) => item.enabled).length} services enabled
        </div>
      </motion.div>

      <GrowthSocialPilotConsole />
      <GrowthPaidCampaignApprovalConsole />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {summaryCards.map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.label} className="glass-card p-4">
              <Icon className="h-5 w-5 text-electric-300" />
              <div className="mt-3 text-2xl font-bold text-white">
                {card.value}
              </div>
              <div className="text-xs text-white/35">{card.label}</div>
            </div>
          );
        })}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="relative w-full max-w-xl">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search integrations..."
              className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none"
            />
          </div>
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          >
            <option value="all" className="bg-space-800">
              All categories
            </option>
            <option value="ai" className="bg-space-800">
              AI Runtime
            </option>
            <option value="source" className="bg-space-800">
              Source Control
            </option>
            <option value="cloud" className="bg-space-800">
              Cloud
            </option>
            <option value="data" className="bg-space-800">
              Data
            </option>
            <option value="security" className="bg-space-800">
              Security
            </option>
            <option value="communication" className="bg-space-800">
              Communication
            </option>
          </select>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-electric-300">
          <Activity className="h-3.5 w-3.5" />
          {message}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {loading ? (
          <div className="glass-card p-8 text-center text-sm text-white/40 xl:col-span-2">
            Loading live integrations…
          </div>
        ) : visible.length === 0 ? (
          <div className="glass-card p-8 text-center text-sm text-white/40 xl:col-span-2">
            No integrations match the selected filters.
          </div>
        ) : (
          visible.map((item, index) => {
            const Icon = icons[item.category] ?? PlugZap;
            const displayStatus = item.enabled ? item.status : "disabled";
            return (
              <motion.div
                key={item.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className="glass-card p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3">
                    <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                      <Icon className="h-5 w-5 text-electric-300" />
                    </div>
                    <div>
                      <h2 className="text-sm font-semibold text-white">
                        {item.name}
                      </h2>
                      <p className="mt-1 text-xs text-white/40">
                        {item.provider} · {item.category}
                      </p>
                    </div>
                  </div>
                  <span
                    className={`rounded-full border px-2.5 py-1 text-xs ${statusClass(displayStatus)}`}
                  >
                    {displayStatus}
                  </span>
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3">
                  <div className="rounded-lg bg-white/[0.02] p-3">
                    <div className="text-[10px] uppercase tracking-wider text-white/30">
                      Endpoint
                    </div>
                    <div className="mt-1 truncate text-sm font-semibold text-white">
                      {item.endpoint}
                    </div>
                  </div>
                  <div className="rounded-lg bg-white/[0.02] p-3">
                    <div className="text-[10px] uppercase tracking-wider text-white/30">
                      Enabled
                    </div>
                    <div className="mt-1 text-sm font-semibold text-white">
                      {item.enabled ? "Yes" : "No"}
                    </div>
                  </div>
                  <div className="rounded-lg bg-white/[0.02] p-3">
                    <div className="text-[10px] uppercase tracking-wider text-white/30">
                      Last check
                    </div>
                    <div className="mt-1 text-sm font-semibold text-white">
                      {item.lastCheck}
                    </div>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    disabled={
                      busy ||
                      item.protected ||
                      (!item.configured && !item.enabled)
                    }
                    onClick={() => toggleIntegration(item)}
                    className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/70 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {item.enabled ? (
                      <ToggleRight className="mr-1 inline h-3.5 w-3.5" />
                    ) : (
                      <ToggleLeft className="mr-1 inline h-3.5 w-3.5" />
                    )}
                    {item.protected
                      ? "Core integration"
                      : !item.configured
                        ? "Credentials required"
                        : item.enabled
                          ? "Disable"
                          : "Enable"}
                  </button>
                  <button
                    disabled={busy || !item.configured}
                    onClick={() => void execute(item.id, "health-check")}
                    className="rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Verify configuration
                  </button>
                </div>
              </motion.div>
            );
          })
        )}
      </div>
    </div>
  );
}
