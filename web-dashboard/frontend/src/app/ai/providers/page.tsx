"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Plug, RefreshCw, Search } from "lucide-react";
import { apiClient } from "@/lib/api-client";

type CatalogProvider = {
  type: string;
  configured: boolean;
  enabled: boolean;
  status: string;
  models: Array<Record<string, unknown>>;
};

export default function AIProvidersPage() {
  const [items, setItems] = useState<CatalogProvider[]>([]);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("Loading provider catalog...");

  async function load() {
    try {
      const rows = await apiClient.get<CatalogProvider[]>("/ai/providers/catalog/supported");
      setItems(rows);
      setMessage("Provider catalog synchronized.");
    } catch {
      setItems([]);
      setMessage("Provider catalog is unavailable.");
    }
  }

  useEffect(() => { void load(); }, []);
  const visible = useMemo(() => items.filter((item) => item.type.toLowerCase().includes(query.toLowerCase())), [items, query]);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-bold text-white tracking-tight">AI Providers</h1>
        <p className="mt-1 text-sm text-white/40">Final provider contract, truthful activation state, capabilities and model discovery.</p>
      </motion.div>
      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search providers..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none" />
          </div>
          <button onClick={() => void load()} className="btn-primary"><RefreshCw className="h-4 w-4" />Refresh</button>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-electric-300"><Activity className="h-3.5 w-3.5" />{message}</div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {visible.map((provider, index) => (
          <motion.section key={provider.type} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.02 }} className="glass-card p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/[0.05]"><Plug className="h-5 w-5 text-electric-300" /></div><div><h2 className="font-semibold text-white">{provider.type}</h2><div className="text-xs text-white/40">{provider.models.length} model contract(s)</div></div></div>
              <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-xs text-white/65">{provider.configured ? (provider.enabled ? provider.status : "disabled") : "unconfigured"}</span>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-3 text-xs text-white/45"><div>Configured<br/><span className="text-white">{provider.configured ? "yes" : "no"}</span></div><div>Enabled<br/><span className="text-white">{provider.enabled ? "yes" : "no"}</span></div><div>Models<br/><span className="text-white">{provider.models.length}</span></div></div>
          </motion.section>
        ))}
      </div>
    </div>
  );
}
