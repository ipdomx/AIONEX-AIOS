"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Cloud, Database, GitBranch, Globe2, PlugZap, Search, Server, ShieldCheck, ToggleLeft, ToggleRight, Wrench } from "lucide-react";

type Integration = {
  id: string;
  name: string;
  category: "cloud" | "source" | "database" | "security" | "communication" | "runtime";
  provider: string;
  status: "connected" | "degraded" | "disabled" | "pending";
  enabled: boolean;
  latency: number;
  projects: number;
  lastCheck: string;
};

type SummaryCard = {
  label: string;
  value: number;
  icon: React.ElementType;
};

const initialIntegrations: Integration[] = [
  { id: "openai", name: "OpenAI", category: "runtime", provider: "OpenAI", status: "connected", enabled: true, latency: 142, projects: 8, lastCheck: "Just now" },
  { id: "github", name: "GitHub", category: "source", provider: "GitHub", status: "connected", enabled: true, latency: 86, projects: 12, lastCheck: "1m ago" },
  { id: "digitalocean", name: "DigitalOcean", category: "cloud", provider: "DigitalOcean", status: "connected", enabled: true, latency: 118, projects: 5, lastCheck: "2m ago" },
  { id: "postgres", name: "PostgreSQL", category: "database", provider: "PostgreSQL", status: "connected", enabled: true, latency: 12, projects: 9, lastCheck: "Just now" },
  { id: "cloudflare", name: "Cloudflare", category: "security", provider: "Cloudflare", status: "degraded", enabled: true, latency: 244, projects: 7, lastCheck: "3m ago" },
  { id: "whatsapp", name: "WhatsApp Owner Channel", category: "communication", provider: "Meta", status: "pending", enabled: false, latency: 0, projects: 1, lastCheck: "Awaiting setup" },
];

const statusClass: Record<Integration["status"], string> = {
  connected: "border-green-500/20 bg-green-500/10 text-green-400",
  degraded: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  disabled: "border-white/10 bg-white/[0.03] text-white/35",
  pending: "border-blue-500/20 bg-blue-500/10 text-blue-300",
};

const icons: Record<Integration["category"], React.ElementType> = {
  cloud: Cloud,
  source: GitBranch,
  database: Database,
  security: ShieldCheck,
  communication: Globe2,
  runtime: Server,
};

export default function OwnerIntegrationsPage() {
  const [items, setItems] = useState(initialIntegrations);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<"all" | Integration["category"]>("all");
  const [message, setMessage] = useState("Integration registry synchronized.");

  const visible = useMemo(
    () => items.filter((item) => {
      const matchesQuery = item.name.toLowerCase().includes(query.toLowerCase()) || item.provider.toLowerCase().includes(query.toLowerCase());
      const matchesCategory = category === "all" || item.category === category;
      return matchesQuery && matchesCategory;
    }),
    [items, query, category],
  );

  const summaryCards: SummaryCard[] = [
    { label: "Connected", value: items.filter((item) => item.status === "connected").length, icon: PlugZap },
    { label: "Degraded", value: items.filter((item) => item.status === "degraded").length, icon: Activity },
    { label: "Disabled", value: items.filter((item) => !item.enabled).length, icon: ToggleLeft },
    { label: "Projects", value: items.reduce((total, item) => total + item.projects, 0), icon: Wrench },
  ];

  function toggleIntegration(id: string) {
    setItems((current) => current.map((item) => {
      if (item.id !== id) return item;
      const enabled = !item.enabled;
      return { ...item, enabled, status: enabled ? "connected" : "disabled" };
    }));
    setMessage(`Owner service control updated for ${id}.`);
  }

  function runHealthCheck(id: string) {
    setItems((current) => current.map((item) => item.id === id ? { ...item, lastCheck: "Just now", latency: item.enabled ? Math.max(10, item.latency || 120) : 0 } : item));
    setMessage(`Health check completed for ${id}.`);
  }

  function connectPending(id: string) {
    setItems((current) => current.map((item) => item.id === id ? { ...item, enabled: true, status: "connected", latency: 120, lastCheck: "Just now" } : item));
    setMessage(`Integration connected: ${id}.`);
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><PlugZap className="h-3.5 w-3.5" /> Owner Integration Registry</div>
          <h1 className="text-3xl font-bold tracking-tight text-white">External Services & Providers</h1>
          <p className="mt-2 text-sm text-white/45">Owner control for AI providers, source control, cloud platforms, databases, security and communication channels.</p>
        </div>
        <div className="rounded-xl border border-green-500/20 bg-green-500/10 px-4 py-2.5 text-sm text-green-300">{items.filter((item) => item.enabled).length} services enabled</div>
      </motion.div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {summaryCards.map((card) => {
          const Icon = card.icon;
          return <div key={card.label} className="glass-card p-4"><Icon className="h-5 w-5 text-electric-300" /><div className="mt-3 text-2xl font-bold text-white">{card.value}</div><div className="text-xs text-white/35">{card.label}</div></div>;
        })}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="relative w-full max-w-xl"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search integrations..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none" /></div>
          <select value={category} onChange={(event) => setCategory(event.target.value as typeof category)} className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"><option value="all" className="bg-space-800">All categories</option><option value="runtime" className="bg-space-800">AI Runtime</option><option value="source" className="bg-space-800">Source Control</option><option value="cloud" className="bg-space-800">Cloud</option><option value="database" className="bg-space-800">Database</option><option value="security" className="bg-space-800">Security</option><option value="communication" className="bg-space-800">Communication</option></select>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-electric-300"><Activity className="h-3.5 w-3.5" />{message}</div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {visible.map((item, index) => {
          const Icon = icons[item.category];
          return (
            <motion.div key={item.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }} className="glass-card p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3"><div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><Icon className="h-5 w-5 text-electric-300" /></div><div><h2 className="text-sm font-semibold text-white">{item.name}</h2><p className="mt-1 text-xs text-white/40">{item.provider} · {item.category}</p></div></div>
                <span className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[item.status]}`}>{item.status}</span>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-3"><div className="rounded-lg bg-white/[0.02] p-3"><div className="text-[10px] uppercase tracking-wider text-white/30">Latency</div><div className="mt-1 text-sm font-semibold text-white">{item.latency}ms</div></div><div className="rounded-lg bg-white/[0.02] p-3"><div className="text-[10px] uppercase tracking-wider text-white/30">Projects</div><div className="mt-1 text-sm font-semibold text-white">{item.projects}</div></div><div className="rounded-lg bg-white/[0.02] p-3"><div className="text-[10px] uppercase tracking-wider text-white/30">Last check</div><div className="mt-1 text-sm font-semibold text-white">{item.lastCheck}</div></div></div>
              <div className="mt-4 flex flex-wrap gap-2"><button onClick={() => toggleIntegration(item.id)} className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/70">{item.enabled ? <ToggleRight className="mr-1 inline h-3.5 w-3.5" /> : <ToggleLeft className="mr-1 inline h-3.5 w-3.5" />}{item.enabled ? "Disable" : "Enable"}</button><button onClick={() => runHealthCheck(item.id)} className="rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-300">Health check</button>{item.status === "pending" && <button onClick={() => connectPending(item.id)} className="rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300">Connect</button>}</div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
