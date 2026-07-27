"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Bot, Cloud, Coins, Database, Server, ShieldCheck, TrendingUp } from "lucide-react";

type BudgetItem = {
  id: string;
  service: string;
  category: string;
  monthlyLimit: number;
  used: number;
  enabled: boolean;
};

const startingBudgets: BudgetItem[] = [
  { id: "openai", service: "OpenAI", category: "AI Provider", monthlyLimit: 5000, used: 3180, enabled: true },
  { id: "anthropic", service: "Anthropic", category: "AI Provider", monthlyLimit: 3500, used: 1970, enabled: true },
  { id: "digitalocean", service: "DigitalOcean", category: "Infrastructure", monthlyLimit: 2400, used: 1810, enabled: true },
  { id: "aws", service: "AWS", category: "Infrastructure", monthlyLimit: 6000, used: 4630, enabled: true },
  { id: "database", service: "Managed Databases", category: "Data", monthlyLimit: 1800, used: 960, enabled: true },
];

const iconFor = (category: string) => category === "AI Provider" ? Bot : category === "Infrastructure" ? Cloud : Database;

export default function OwnerCostsPage() {
  const [budgets, setBudgets] = useState(startingBudgets);
  const totalLimit = useMemo(() => budgets.reduce((sum, item) => sum + item.monthlyLimit, 0), [budgets]);
  const totalUsed = useMemo(() => budgets.reduce((sum, item) => sum + item.used, 0), [budgets]);

  function updateLimit(id: string, value: number) {
    setBudgets((current) => current.map((item) => item.id === id ? { ...item, monthlyLimit: Math.max(value, item.used) } : item));
  }

  function toggleService(id: string) {
    setBudgets((current) => current.map((item) => item.id === id ? { ...item, enabled: !item.enabled } : item));
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300"><Coins className="h-3.5 w-3.5" /> Owner Cost Governance</div>
        <h1 className="mt-3 text-3xl font-bold text-white">Cost, Usage & Service Limits</h1>
        <p className="mt-2 text-sm text-white/45">Set owner-controlled budgets, suspend expensive services and monitor consumption across AI providers and infrastructure.</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {[{ label: "Monthly Budget", value: `$${totalLimit.toLocaleString()}`, icon: ShieldCheck }, { label: "Used", value: `$${totalUsed.toLocaleString()}`, icon: TrendingUp }, { label: "Remaining", value: `$${(totalLimit - totalUsed).toLocaleString()}`, icon: Coins }, { label: "Active Services", value: budgets.filter((item) => item.enabled).length.toString(), icon: Server }].map((item) => {
          const Icon = item.icon;
          return <div key={item.label} className="glass-card p-5"><div className="flex items-center justify-between"><Icon className="h-5 w-5 text-electric-300" /><span className="text-2xl font-bold text-white">{item.value}</span></div><p className="mt-3 text-xs uppercase tracking-wider text-white/35">{item.label}</p></div>;
        })}
      </div>

      {totalUsed / totalLimit > 0.75 && <div className="glass-card flex items-start gap-3 border border-orange-500/20 p-4 text-orange-200"><AlertTriangle className="mt-0.5 h-5 w-5" /><div><p className="text-sm font-semibold">Owner attention required</p><p className="mt-1 text-xs text-orange-200/65">Combined monthly usage is above 75% of the approved budget.</p></div></div>}

      <div className="space-y-4">
        {budgets.map((item, index) => {
          const Icon = iconFor(item.category);
          const percentage = Math.min(100, Math.round((item.used / item.monthlyLimit) * 100));
          return (
            <motion.div key={item.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }} className="glass-card p-5">
              <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex min-w-0 items-start gap-3"><div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><Icon className="h-5 w-5 text-electric-300" /></div><div><h2 className="text-sm font-semibold text-white">{item.service}</h2><p className="mt-1 text-xs text-white/35">{item.category}</p></div></div>
                <div className="w-full max-w-xl space-y-2"><div className="flex items-center justify-between text-xs"><span className="text-white/40">${item.used.toLocaleString()} used</span><span className="text-white/65">${item.monthlyLimit.toLocaleString()} limit</span></div><div className="h-2 overflow-hidden rounded-full bg-white/[0.06]"><div className={`h-full rounded-full ${percentage >= 90 ? "bg-red-500" : percentage >= 75 ? "bg-orange-500" : "bg-electric-500"}`} style={{ width: `${percentage}%` }} /></div></div>
                <div className="flex flex-wrap items-center gap-2"><input type="number" min={item.used} value={item.monthlyLimit} onChange={(event) => updateLimit(item.id, Number(event.target.value))} className="glass-input w-32 rounded-xl px-3 py-2 text-sm text-white outline-none" /><button type="button" onClick={() => toggleService(item.id)} className={`rounded-xl border px-4 py-2 text-xs font-medium transition ${item.enabled ? "border-green-500/20 bg-green-500/10 text-green-300 hover:bg-green-500/15" : "border-red-500/20 bg-red-500/10 text-red-300 hover:bg-red-500/15"}`}>{item.enabled ? "Enabled" : "Suspended"}</button></div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
