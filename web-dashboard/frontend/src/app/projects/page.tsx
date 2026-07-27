"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { FolderOpen, Plus, Search, Users, AlertCircle, Loader2, X } from "lucide-react";
import { useSearchParams } from "next/navigation";

import { ProjectSummary, runtimeServices } from "@/lib/runtime-services";

export default function ProjectsPage() {
  const searchParams = useSearchParams();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(searchParams.get("create") === "1");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("medium");

  async function loadProjects() {
    setLoading(true);
    setError(null);
    try {
      setProjects(await runtimeServices.listProjects({ limit: 100 }));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to load projects");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadProjects(); }, []);

  async function createProject(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const created = await runtimeServices.createProject({
        name,
        description: description || null,
        priority,
        workspace_id: "workspace-engineering",
        tags: [],
      });
      setProjects((current) => [created, ...current]);
      setName("");
      setDescription("");
      setPriority("medium");
      setShowCreate(false);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to create project");
    } finally {
      setCreating(false);
    }
  }

  const filteredProjects = useMemo(
    () => projects.filter((project) => project.name.toLowerCase().includes(searchQuery.toLowerCase()) && (statusFilter === "all" || project.status === statusFilter)),
    [projects, searchQuery, statusFilter],
  );

  const getPriorityColor = (value: string) => value === "critical" ? "bg-red-500/10 text-red-400 border-red-500/20" : value === "high" ? "bg-orange-500/10 text-orange-400 border-orange-500/20" : value === "medium" ? "bg-blue-500/10 text-blue-400 border-blue-500/20" : "bg-white/10 text-white/40 border-white/20";

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold text-white tracking-tight">Projects</h1><p className="text-sm text-white/40 mt-1">Live projects loaded from the AIOS backend</p></div>
        <button onClick={() => setShowCreate(true)} className="btn-primary"><Plus className="w-4 h-4" />New Project</button>
      </motion.div>

      {showCreate && (
        <form onSubmit={createProject} className="glass-card p-5 space-y-4">
          <div className="flex items-center justify-between"><h2 className="text-sm font-semibold text-white">Create project</h2><button type="button" onClick={() => setShowCreate(false)} className="p-1.5 rounded-lg hover:bg-white/[0.06]"><X className="w-4 h-4 text-white/50" /></button></div>
          <input required minLength={2} value={name} onChange={(event) => setName(event.target.value)} placeholder="Project name" className="w-full px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none" />
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Description" className="w-full px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none min-h-24" />
          <select value={priority} onChange={(event) => setPriority(event.target.value)} className="w-full px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none"><option value="low" className="bg-space-800">Low</option><option value="medium" className="bg-space-800">Medium</option><option value="high" className="bg-space-800">High</option><option value="critical" className="bg-space-800">Critical</option></select>
          <button disabled={creating} className="btn-primary">{creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}{creating ? "Creating" : "Create Project"}</button>
        </form>
      )}

      <div className="flex items-center gap-3"><div className="relative flex-1 max-w-md"><Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" /><input type="text" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search projects..." className="w-full pl-10 pr-4 py-2.5 rounded-xl glass-input text-sm text-white placeholder-white/30 outline-none" /></div><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none"><option value="all" className="bg-space-800">All Status</option><option value="active" className="bg-space-800">Active</option><option value="planning" className="bg-space-800">Planning</option><option value="paused" className="bg-space-800">Paused</option><option value="completed" className="bg-space-800">Completed</option></select></div>

      {loading && <div className="glass-card p-8 flex items-center justify-center gap-3 text-white/60"><Loader2 className="w-5 h-5 animate-spin" /> Loading projects...</div>}
      {error && <div className="glass-card p-5 border border-red-500/20 flex items-start gap-3 text-red-300"><AlertCircle className="w-5 h-5 mt-0.5" /><div><p className="font-semibold">Request failed</p><p className="text-sm text-red-300/70 mt-1">{error}</p></div></div>}
      {!loading && <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">{filteredProjects.map((project, index) => <motion.div key={project.id} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + index * 0.05 }} className="glass-card p-5"><div className="flex items-start justify-between mb-4"><div className="flex items-center gap-3"><div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/20 flex items-center justify-center border border-white/[0.08]"><FolderOpen className="w-5 h-5 text-blue-400" /></div><div><h3 className="text-sm font-semibold text-white">{project.name}</h3><p className="text-xs text-white/40">{project.workspace}</p></div></div><span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${getPriorityColor(project.priority)}`}>{project.priority}</span></div><div className="mb-4"><div className="flex items-center justify-between mb-2"><span className="text-xs text-white/40">Progress</span><span className="text-xs font-medium text-white">{project.progress}%</span></div><div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden"><motion.div initial={{ width: 0 }} animate={{ width: `${project.progress}%` }} className="h-full rounded-full bg-gradient-to-r from-blue-500 to-cyan-500" /></div></div><div className="grid grid-cols-2 gap-2 mb-4"><div className="text-center p-2 rounded-lg bg-white/[0.02]"><div className="text-xs font-bold text-white">{project.task_count}</div><div className="text-[10px] text-white/30">Tasks</div></div><div className="text-center p-2 rounded-lg bg-white/[0.02]"><div className="text-xs font-bold text-white">{project.team_count}</div><div className="text-[10px] text-white/30">Members</div></div></div><div className="flex items-center justify-between pt-3 border-t border-white/[0.06]"><div className="flex items-center gap-2"><Users className="w-3.5 h-3.5 text-white/30" /><span className="text-xs text-white/40">Owner: {project.owner}</span></div><span className="text-[10px] text-white/30">{project.status}</span></div></motion.div>)}</div>}
    </div>
  );
}