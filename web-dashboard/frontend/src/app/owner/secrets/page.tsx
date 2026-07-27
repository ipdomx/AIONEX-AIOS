"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { KeyRound, LockKeyhole, Plus, RefreshCw, Search, ShieldCheck, Trash2 } from "lucide-react";

type SecretRecord = {
  id: string;
  name: string;
  scope: "global" | "organization" | "project" | "service";
  provider: string;
  status: "active" | "rotating" | "expired" | "revoked";
  lastRotated: string;
  maskedValue: string;
};

const initialSecrets: SecretRecord[] = [
  { id: "sec-openai", name: "OPENAI_API_KEY", scope: "global", provider: "OpenAI", status: "active", lastRotated: "2026-07-21", maskedValue: "sk-proj-••••••••••••" },
  { id: "sec-do", name: "DIGITALOCEAN_TOKEN", scope: "organization", provider: "DigitalOcean", status: "rotating", lastRotated: "2026-07-18", maskedValue: "dop_v1_••••••••••••" },
  { id: "sec-cloudflare", name: "CLOUDFLARE_API_TOKEN", scope: "service", provider: "Cloudflare", status: "active", lastRotated: "2026-07-10", maskedValue: "cf_••••••••••••" },
  { id: "sec-db", name: "POSTGRES_OWNER_PASSWORD", scope: "project", provider: "PostgreSQL", status: "expired", lastRotated: "2026-06-01", maskedValue: "••••••••••••••••" },
];

const statusClass: Record<SecretRecord["status"], string> = {
  active: "border-green-500/20 bg-green-500/10 text-green-400",
  rotating: "border-blue-500/20 bg-blue-500/10 text-blue-300",
  expired: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  revoked: "border-red-500/20 bg-red-500/10 text-red-400",
};

export default function OwnerSecretsPage() {
  const [secrets, setSecrets] = useState(initialSecrets);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"all" | SecretRecord["scope"]>("all");
  const [message, setMessage] = useState("Secrets vault synchronized.");

  const filtered = useMemo(() => secrets.filter((secret) => {
    const matchesQuery = `${secret.name} ${secret.provider}`.toLowerCase().includes(query.toLowerCase());
    const matchesScope = scope === "all" || secret.scope === scope;
    return matchesQuery && matchesScope;
  }), [query, scope, secrets]);

  function rotateSecret(id: string) {
    setSecrets((items) => items.map((item) => item.id === id ? { ...item, status: "active", lastRotated: new Date().toISOString().slice(0, 10) } : item));
    setMessage(`Rotation completed for ${id}.`);
  }

  function revokeSecret(id: string) {
    setSecrets((items) => items.map((item) => item.id === id ? { ...item, status: "revoked" } : item));
    setMessage(`Secret ${id} revoked by owner.`);
  }

  function addSecret() {
    const id = `sec-${Date.now()}`;
    setSecrets((items) => [{ id, name: "NEW_SECRET", scope: "project", provider: "Custom", status: "active", lastRotated: new Date().toISOString().slice(0, 10), maskedValue: "••••••••••••" }, ...items]);
    setMessage("New protected secret record created.");
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><LockKeyhole className="h-3.5 w-3.5" /> Owner Secrets & Keys</div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Secrets, Credentials & Rotation Authority</h1>
          <p className="mt-2 text-sm text-white/45">Owner-only control for protected API keys, service credentials, rotation state and revocation.</p>
        </div>
        <button onClick={addSecret} className="btn-primary"><Plus className="h-4 w-4" />Add protected secret</button>
      </motion.div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          ["Total", secrets.length],
          ["Active", secrets.filter((item) => item.status === "active").length],
          ["Rotating", secrets.filter((item) => item.status === "rotating").length],
          ["Needs action", secrets.filter((item) => item.status === "expired" || item.status === "revoked").length],
        ].map(([label, value]) => <div key={String(label)} className="glass-card p-4"><KeyRound className="h-5 w-5 text-electric-300" /><div className="mt-3 text-2xl font-bold text-white">{String(value)}</div><div className="text-xs text-white/35">{String(label)}</div></div>)}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full max-w-xl"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search secrets and providers..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none" /></div>
          <select value={scope} onChange={(event) => setScope(event.target.value as typeof scope)} className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"><option value="all" className="bg-space-800">All scopes</option><option value="global" className="bg-space-800">Global</option><option value="organization" className="bg-space-800">Organization</option><option value="project" className="bg-space-800">Project</option><option value="service" className="bg-space-800">Service</option></select>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-electric-300"><ShieldCheck className="h-3.5 w-3.5" />{message}</div>
      </div>

      <div className="space-y-3">
        {filtered.map((secret, index) => (
          <motion.div key={secret.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }} className="glass-card p-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div><h2 className="text-sm font-semibold text-white">{secret.name}</h2><p className="mt-1 text-xs text-white/40">{secret.provider} · {secret.scope} · Last rotated {secret.lastRotated}</p><code className="mt-2 inline-block rounded-lg bg-black/20 px-3 py-1.5 text-xs text-white/50">{secret.maskedValue}</code></div>
              <div className="flex flex-wrap items-center gap-2"><span className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[secret.status]}`}>{secret.status}</span><button onClick={() => rotateSecret(secret.id)} className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-xs text-blue-300"><RefreshCw className="mr-1 inline h-3.5 w-3.5" />Rotate</button><button onClick={() => revokeSecret(secret.id)} className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300"><Trash2 className="mr-1 inline h-3.5 w-3.5" />Revoke</button></div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
