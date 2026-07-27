"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Building2, CheckCircle2, CreditCard, PauseCircle, ReceiptText, Search, ShieldCheck, WalletCards } from "lucide-react";

type Plan = "Free" | "Team" | "Enterprise";
type Status = "active" | "trial" | "past_due" | "suspended";

type Account = {
  id: string;
  organization: string;
  plan: Plan;
  status: Status;
  monthlyLimit: number;
  usage: number;
  seats: number;
  renewal: string;
};

const initialAccounts: Account[] = [
  { id: "org-aionex", organization: "AIONEX Corp", plan: "Enterprise", status: "active", monthlyLimit: 18000, usage: 12340, seats: 120, renewal: "2026-08-01" },
  { id: "org-north", organization: "Northstar Labs", plan: "Team", status: "trial", monthlyLimit: 3500, usage: 1480, seats: 18, renewal: "2026-08-09" },
  { id: "org-atlas", organization: "Atlas Systems", plan: "Enterprise", status: "past_due", monthlyLimit: 12000, usage: 11420, seats: 74, renewal: "2026-07-31" },
  { id: "org-solo", organization: "Solo Studio", plan: "Free", status: "active", monthlyLimit: 300, usage: 214, seats: 2, renewal: "2026-08-15" },
];

const statusClass: Record<Status, string> = {
  active: "border-green-500/20 bg-green-500/10 text-green-400",
  trial: "border-blue-500/20 bg-blue-500/10 text-blue-300",
  past_due: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  suspended: "border-red-500/20 bg-red-500/10 text-red-400",
};

export default function OwnerBillingPage() {
  const [accounts, setAccounts] = useState(initialAccounts);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("Billing controls ready.");

  const visible = useMemo(() => accounts.filter((account) => account.organization.toLowerCase().includes(query.toLowerCase())), [accounts, query]);
  const monthlyRevenue = accounts.reduce((total, account) => total + (account.plan === "Enterprise" ? 4999 : account.plan === "Team" ? 699 : 0), 0);

  function changePlan(id: string, plan: Plan) {
    setAccounts((items) => items.map((item) => item.id === id ? { ...item, plan } : item));
    setMessage(`Plan updated for ${id}: ${plan}`);
  }

  function toggleSuspension(id: string) {
    setAccounts((items) => items.map((item) => item.id === id ? { ...item, status: item.status === "suspended" ? "active" : "suspended" } : item));
    setMessage(`Subscription state changed for ${id}.`);
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><WalletCards className="h-3.5 w-3.5" /> Owner Billing Authority</div>
        <h1 className="text-3xl font-bold tracking-tight text-white">Subscriptions, Plans & Billing</h1>
        <p className="mt-2 text-sm text-white/45">Control organization plans, seats, limits, renewal state and billing enforcement.</p>
      </motion.div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="glass-card p-4"><CreditCard className="h-5 w-5 text-electric-300" /><div className="mt-3 text-2xl font-bold text-white">€{monthlyRevenue.toLocaleString()}</div><div className="text-xs text-white/35">Monthly recurring revenue</div></div>
        <div className="glass-card p-4"><Building2 className="h-5 w-5 text-electric-300" /><div className="mt-3 text-2xl font-bold text-white">{accounts.length}</div><div className="text-xs text-white/35">Organizations</div></div>
        <div className="glass-card p-4"><ReceiptText className="h-5 w-5 text-electric-300" /><div className="mt-3 text-2xl font-bold text-white">{accounts.filter((item) => item.status === "past_due").length}</div><div className="text-xs text-white/35">Past due</div></div>
        <div className="glass-card p-4"><ShieldCheck className="h-5 w-5 text-electric-300" /><div className="mt-3 text-2xl font-bold text-white">{accounts.filter((item) => item.status === "active").length}</div><div className="text-xs text-white/35">Active</div></div>
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full max-w-xl"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search organizations..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none" /></div>
          <div className="flex items-center gap-2 text-xs text-electric-300"><CheckCircle2 className="h-3.5 w-3.5" />{message}</div>
        </div>
      </div>

      <div className="space-y-3">
        {visible.map((account, index) => {
          const percent = Math.min(100, Math.round((account.usage / account.monthlyLimit) * 100));
          return (
            <motion.div key={account.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }} className="glass-card p-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div><h2 className="text-sm font-semibold text-white">{account.organization}</h2><p className="mt-1 text-xs text-white/40">{account.plan} · {account.seats} seats · renews {account.renewal}</p><div className="mt-3 h-1.5 w-64 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full rounded-full bg-gradient-to-r from-blue-500 to-cyan-500" style={{ width: `${percent}%` }} /></div><p className="mt-1 text-[10px] text-white/30">Usage €{account.usage.toLocaleString()} / €{account.monthlyLimit.toLocaleString()}</p></div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[account.status]}`}>{account.status}</span>
                  <select value={account.plan} onChange={(event) => changePlan(account.id, event.target.value as Plan)} className="glass-input rounded-lg px-3 py-2 text-xs text-white outline-none"><option className="bg-space-800">Free</option><option className="bg-space-800">Team</option><option className="bg-space-800">Enterprise</option></select>
                  <button onClick={() => toggleSuspension(account.id)} className="rounded-lg border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300"><PauseCircle className="mr-1 inline h-3.5 w-3.5" />{account.status === "suspended" ? "Reactivate" : "Suspend"}</button>
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
