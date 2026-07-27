"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Bot, CheckCircle2, Cloud, Database, Globe2, Lock, Server, Shield, ToggleLeft, ToggleRight, Workflow } from "lucide-react";

type Service = {
  id: string;
  name: string;
  category: string;
  description: string;
  enabled: boolean;
  scope: string;
  icon: React.ElementType;
};

const initialServices: Service[] = [
  { id: "openai", name: "OpenAI", category: "AI Providers", description: "Chat, vision, embeddings, image and audio interfaces.", enabled: true, scope: "All owner projects", icon: Bot },
  { id: "anthropic", name: "Anthropic", category: "AI Providers", description: "Claude messages, tools, vision and streaming.", enabled: true, scope: "Selected organizations", icon: Bot },
  { id: "gemini", name: "Gemini", category: "AI Providers", description: "Models, files, vision, tools and safety controls.", enabled: false, scope: "Disabled by owner", icon: Bot },
  { id: "github", name: "GitHub", category: "Engineering", description: "Repositories, issues, pull requests and release automation.", enabled: true, scope: "Engineering workspace", icon: Workflow },
  { id: "digitalocean", name: "DigitalOcean", category: "Cloud", description: "Droplets, networking, storage and managed services.", enabled: true, scope: "Infrastructure team", icon: Cloud },
  { id: "aws", name: "AWS", category: "Cloud", description: "Compute, storage, networking and managed databases.", enabled: false, scope: "Owner approval required", icon: Cloud },
  { id: "postgres", name: "PostgreSQL", category: "Data", description: "Primary operational and identity datastore.", enabled: true, scope: "Core platform", icon: Database },
  { id: "redis", name: "Redis", category: "Data", description: "Cache, sessions, queues and distributed coordination.", enabled: true, scope: "Core platform", icon: Database },
  { id: "cloudflare", name: "Cloudflare", category: "Security", description: "DNS, CDN, WAF and edge protection controls.", enabled: false, scope: "Pending setup", icon: Shield },
  { id: "vault", name: "Secrets Vault", category: "Security", description: "Protected secrets and credentials lifecycle management.", enabled: true, scope: "Owner-only control", icon: Lock },
  { id: "servers", name: "Server Runtime", category: "Infrastructure", description: "SSH, deployment, health and recovery operations.", enabled: true, scope: "Operations", icon: Server },
  { id: "public-api", name: "Public API", category: "Platform", description: "External API access for approved organizations and clients.", enabled: false, scope: "Owner disabled", icon: Globe2 },
];

export default function OwnerServicesPage() {
  const [services, setServices] = useState(initialServices);
  const [category, setCategory] = useState("All");
  const categories = useMemo(() => ["All", ...Array.from(new Set(services.map((service) => service.category)))], [services]);
  const visible = category === "All" ? services : services.filter((service) => service.category === category);
  const enabledCount = services.filter((service) => service.enabled).length;

  function toggleService(id: string) {
    setServices((current) => current.map((service) => service.id === id ? { ...service, enabled: !service.enabled } : service));
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Owner Service Control</h1>
          <p className="mt-1 text-sm text-white/40">Enable, suspend and scope platform services from one owner-only center.</p>
        </div>
        <div className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.03] px-4 py-3">
          <CheckCircle2 className="h-5 w-5 text-green-400" />
          <div><div className="text-sm font-semibold text-white">{enabledCount} enabled</div><div className="text-[10px] text-white/35">of {services.length} services</div></div>
        </div>
      </motion.div>

      <div className="flex flex-wrap gap-2">
        {categories.map((item) => <button key={item} onClick={() => setCategory(item)} className={`rounded-xl px-4 py-2 text-xs font-medium transition ${category === item ? "bg-electric-500/15 text-electric-300 border border-electric-500/20" : "glass text-white/45 hover:text-white/75"}`}>{item}</button>)}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {visible.map((service, index) => {
          const Icon = service.icon;
          return (
            <motion.div key={service.id} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }} className="glass-card p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><Icon className="h-5 w-5 text-electric-300" /></div>
                  <div><h2 className="text-sm font-semibold text-white">{service.name}</h2><p className="text-[10px] uppercase tracking-wider text-white/30">{service.category}</p></div>
                </div>
                <button onClick={() => toggleService(service.id)} aria-label={`Toggle ${service.name}`} className="rounded-lg p-1.5 hover:bg-white/[0.05]">
                  {service.enabled ? <ToggleRight className="h-7 w-7 text-green-400" /> : <ToggleLeft className="h-7 w-7 text-white/25" />}
                </button>
              </div>
              <p className="mt-4 text-xs leading-relaxed text-white/40">{service.description}</p>
              <div className="mt-4 flex items-center justify-between border-t border-white/[0.05] pt-3 text-[10px]"><span className="text-white/30">{service.scope}</span><span className={service.enabled ? "text-green-400" : "text-orange-400"}>{service.enabled ? "Enabled" : "Suspended"}</span></div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
