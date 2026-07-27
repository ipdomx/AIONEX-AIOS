"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { Activity, BookOpen, Bot, FileText, FolderKanban, Search, Server, ShieldCheck, Users, Workflow } from "lucide-react";

type SearchItem = {
  id: string;
  type: "project" | "user" | "agent" | "workflow" | "server" | "document" | "audit";
  title: string;
  description: string;
  scope: string;
  status: string;
  href: string;
};

const items: SearchItem[] = [
  { id: "project-aios", type: "project", title: "AIONEX AIOS", description: "Enterprise AI operating system project", scope: "AIONEX Corp", status: "active", href: "/projects" },
  { id: "user-owner", type: "user", title: "AIONEX Owner", description: "Protected super owner account", scope: "Global", status: "active", href: "/users" },
  { id: "agent-reviewer", type: "agent", title: "Code Reviewer AI", description: "Engineering review agent", scope: "Engineering", status: "running", href: "/ai/agents" },
  { id: "workflow-release", type: "workflow", title: "Release Quality Gate", description: "Validation and owner approval workflow", scope: "Platform", status: "active", href: "/workflows" },
  { id: "server-dubai", type: "server", title: "api-dubai-01", description: "Primary API server", scope: "Dubai", status: "online", href: "/infrastructure/servers" },
  { id: "doc-policy", type: "document", title: "Owner Governance Policy", description: "Owner authority and approvals policy", scope: "Governance", status: "published", href: "/knowledge" },
  { id: "audit-release", type: "audit", title: "Release approval recorded", description: "Owner approved production release", scope: "Audit", status: "verified", href: "/owner/audit" },
];

const iconMap: Record<SearchItem["type"], React.ElementType> = {
  project: FolderKanban,
  user: Users,
  agent: Bot,
  workflow: Workflow,
  server: Server,
  document: BookOpen,
  audit: ShieldCheck,
};

export default function OwnerGlobalSearchPage() {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | SearchItem["type"]>("all");
  const [status, setStatus] = useState("Ready for owner-wide search.");

  const results = useMemo(() => items.filter((item) => {
    const needle = query.toLowerCase();
    const matchesQuery = !needle || item.title.toLowerCase().includes(needle) || item.description.toLowerCase().includes(needle) || item.scope.toLowerCase().includes(needle);
    const matchesType = typeFilter === "all" || item.type === typeFilter;
    return matchesQuery && matchesType;
  }), [query, typeFilter]);

  function runSearch() {
    setStatus(`Search completed: ${results.length} result${results.length === 1 ? "" : "s"}.`);
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><Search className="h-3.5 w-3.5" /> Owner Global Search</div>
        <h1 className="text-3xl font-bold tracking-tight text-white">Search Everything</h1>
        <p className="mt-2 text-sm text-white/45">Search projects, users, agents, workflows, infrastructure, documents and audit records from one owner-only interface.</p>
      </motion.div>

      <div className="glass-card p-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <div className="relative flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" /><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") runSearch(); }} placeholder="Search across AIOS..." className="glass-input w-full rounded-xl py-3 pl-10 pr-4 text-sm text-white outline-none" /></div>
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as typeof typeFilter)} className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none"><option value="all" className="bg-space-800">All types</option><option value="project" className="bg-space-800">Projects</option><option value="user" className="bg-space-800">Users</option><option value="agent" className="bg-space-800">Agents</option><option value="workflow" className="bg-space-800">Workflows</option><option value="server" className="bg-space-800">Servers</option><option value="document" className="bg-space-800">Documents</option><option value="audit" className="bg-space-800">Audit</option></select>
          <button onClick={runSearch} className="btn-primary"><Search className="h-4 w-4" />Search</button>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-electric-300"><Activity className="h-3.5 w-3.5" />{status}</div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {results.map((item, index) => {
          const Icon = iconMap[item.type];
          return (
            <motion.div key={item.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }}>
              <Link href={item.href} className="glass-card block p-5 transition hover:bg-white/[0.05]">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3"><div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><Icon className="h-5 w-5 text-electric-300" /></div><div><h2 className="text-sm font-semibold text-white">{item.title}</h2><p className="mt-1 text-xs text-white/40">{item.description}</p><p className="mt-2 text-[11px] text-white/30">{item.type} · {item.scope}</p></div></div>
                  <span className="rounded-full border border-green-500/20 bg-green-500/10 px-2.5 py-1 text-xs text-green-300">{item.status}</span>
                </div>
              </Link>
            </motion.div>
          );
        })}
      </div>

      {results.length === 0 && <div className="glass-card p-8 text-center text-sm text-white/40"><FileText className="mx-auto mb-3 h-6 w-6" />No matching owner-visible records.</div>}
    </div>
  );
}
