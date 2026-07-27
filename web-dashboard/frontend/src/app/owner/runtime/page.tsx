"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { Building2, FolderKanban, RefreshCw, ShieldCheck, Users } from "lucide-react";
import { fetchOwnerRuntimeSnapshot, type OwnerRuntimeSnapshot } from "@/lib/owner-runtime";

const emptySnapshot: OwnerRuntimeSnapshot = { generatedAt: "", projects: [], organizations: [], users: [] };

type MetricCard = { label: string; value: number; icon: LucideIcon };

export default function OwnerRuntimePage() {
  const [snapshot, setSnapshot] = useState(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading owner runtime data...");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchOwnerRuntimeSnapshot(signal);
      setSnapshot(data);
      setMessage(`Runtime synchronized at ${new Date(data.generatedAt).toLocaleTimeString()}.`);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage("Runtime refresh failed.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  const totals = useMemo(() => ({
    activeProjects: snapshot.projects.filter((project) => project.status === "active").length,
    activeOrganizations: snapshot.organizations.filter((organization) => organization.status === "active").length,
    activeUsers: snapshot.users.filter((user) => user.status === "active").length,
  }), [snapshot]);

  const metrics: MetricCard[] = [
    { label: "Active projects", value: totals.activeProjects, icon: FolderKanban },
    { label: "Organizations", value: totals.activeOrganizations, icon: Building2 },
    { label: "Active users", value: totals.activeUsers, icon: Users },
  ];

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div><div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><ShieldCheck className="h-3.5 w-3.5" /> Owner Runtime</div><h1 className="text-3xl font-bold tracking-tight text-white">Live Ownership Data</h1><p className="mt-2 text-sm text-white/45">Backend-ready runtime view for projects, organizations and users, with safe fallback data until the production endpoint is available.</p></div>
        <button disabled={loading} onClick={() => void load()} className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />Refresh</button>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">{metrics.map(({ label, value, icon: Icon }) => <div key={label} className="glass-card p-5"><Icon className="h-5 w-5 text-electric-300" /><div className="mt-4 text-3xl font-bold text-white">{value}</div><div className="mt-1 text-xs text-white/40">{label}</div></div>)}</div>
      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <section className="space-y-3"><h2 className="text-sm font-semibold text-white">Projects</h2><div className="grid grid-cols-1 gap-4 xl:grid-cols-2">{snapshot.projects.map((project) => <div key={project.id} className="glass-card p-5"><div className="flex items-start justify-between gap-4"><div><h3 className="text-sm font-semibold text-white">{project.name}</h3><p className="mt-1 text-xs text-white/40">{project.organization} · {project.updatedAt}</p></div><span className="rounded-full border border-green-500/20 bg-green-500/10 px-2.5 py-1 text-xs text-green-300">{project.status}</span></div><div className="mt-4 h-2 overflow-hidden rounded-full bg-white/[0.05]"><div className="h-full rounded-full bg-electric-400" style={{ width: `${Math.min(100, Math.max(0, project.progress))}%` }} /></div><div className="mt-2 text-right text-xs text-white/35">{project.progress}%</div></div>)}</div></section>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2"><section className="space-y-3"><h2 className="text-sm font-semibold text-white">Organizations</h2>{snapshot.organizations.map((organization) => <div key={organization.id} className="glass-card flex items-center justify-between p-4"><div><div className="text-sm font-medium text-white">{organization.name}</div><div className="mt-1 text-xs text-white/35">{organization.users} users · {organization.projects} projects</div></div><span className="text-xs text-green-300">{organization.status}</span></div>)}</section><section className="space-y-3"><h2 className="text-sm font-semibold text-white">Users</h2>{snapshot.users.map((user) => <div key={user.id} className="glass-card flex items-center justify-between p-4"><div><div className="text-sm font-medium text-white">{user.name}</div><div className="mt-1 text-xs text-white/35">{user.role} · {user.organization}</div></div><span className="text-xs text-green-300">{user.status}</span></div>)}</section></div>
    </div>
  );
}
