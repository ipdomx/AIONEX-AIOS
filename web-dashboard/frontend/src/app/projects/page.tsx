"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { FolderOpen, Plus, Search, Users } from "lucide-react";

const projects = [
  { id: "1", name: "Data Pipeline v2", status: "active", priority: "high", progress: 67, workspace: "Engineering", team: 8, tasks: { completed: 30, in_progress: 10, todo: 5 }, tags: ["data", "pipeline"] },
  { id: "2", name: "AI Model Training", status: "active", priority: "critical", progress: 34, workspace: "Research", team: 5, tasks: { completed: 10, in_progress: 12, todo: 6 }, tags: ["ai", "ml"] },
  { id: "3", name: "Customer Portal", status: "planning", priority: "medium", progress: 12, workspace: "Product", team: 6, tasks: { completed: 4, in_progress: 8, todo: 23 }, tags: ["frontend", "customer"] },
  { id: "4", name: "Security Audit", status: "active", priority: "high", progress: 45, workspace: "Security", team: 3, tasks: { completed: 8, in_progress: 7, todo: 3 }, tags: ["security", "audit"] },
  { id: "5", name: "Mobile App v3", status: "paused", priority: "medium", progress: 78, workspace: "Mobile", team: 7, tasks: { completed: 40, in_progress: 5, todo: 7 }, tags: ["mobile", "ios", "android"] },
];

export default function ProjectsPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const filteredProjects = projects.filter((p) => p.name.toLowerCase().includes(searchQuery.toLowerCase()) && (statusFilter === "all" || p.status === statusFilter));

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case "critical": return "bg-red-500/10 text-red-400 border-red-500/20";
      case "high": return "bg-orange-500/10 text-orange-400 border-orange-500/20";
      case "medium": return "bg-blue-500/10 text-blue-400 border-blue-500/20";
      default: return "bg-white/10 text-white/40 border-white/20";
    }
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Projects</h1>
          <p className="text-sm text-white/40 mt-1">Manage and track all projects</p>
        </div>
        <button className="btn-primary"><Plus className="w-4 h-4" />New Project</button>
      </motion.div>
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
          <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search projects..." className="w-full pl-10 pr-4 py-2.5 rounded-xl glass-input text-sm text-white placeholder-white/30 outline-none" />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none">
          <option value="all" className="bg-space-800">All Status</option>
          <option value="active" className="bg-space-800">Active</option>
          <option value="planning" className="bg-space-800">Planning</option>
          <option value="paused" className="bg-space-800">Paused</option>
          <option value="completed" className="bg-space-800">Completed</option>
        </select>
      </motion.div>
      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
        {filteredProjects.map((project, i) => (
          <motion.div key={project.id} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.05 }} className="glass-card p-5">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/20 flex items-center justify-center border border-white/[0.08]">
                  <FolderOpen className="w-5 h-5 text-blue-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">{project.name}</h3>
                  <p className="text-xs text-white/40">{project.workspace}</p>
                </div>
              </div>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${getPriorityColor(project.priority)}`}>{project.priority}</span>
            </div>
            <div className="mb-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-white/40">Progress</span>
                <span className="text-xs font-medium text-white">{project.progress}%</span>
              </div>
              <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
                <motion.div initial={{ width: 0 }} animate={{ width: `${project.progress}%` }} transition={{ duration: 1, delay: 0.3 }} className="h-full rounded-full bg-gradient-to-r from-blue-500 to-cyan-500" />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 mb-4">
              <div className="text-center p-2 rounded-lg bg-white/[0.02]"><div className="text-xs font-bold text-white">{project.tasks.completed}</div><div className="text-[10px] text-white/30">Done</div></div>
              <div className="text-center p-2 rounded-lg bg-white/[0.02]"><div className="text-xs font-bold text-white">{project.tasks.in_progress}</div><div className="text-[10px] text-white/30">Active</div></div>
              <div className="text-center p-2 rounded-lg bg-white/[0.02]"><div className="text-xs font-bold text-white">{project.tasks.todo}</div><div className="text-[10px] text-white/30">Todo</div></div>
            </div>
            <div className="flex items-center justify-between pt-3 border-t border-white/[0.06]">
              <div className="flex items-center gap-2"><Users className="w-3.5 h-3.5 text-white/30" /><span className="text-xs text-white/40">{project.team} members</span></div>
              <div className="flex items-center gap-1">
                {project.tags.map((tag) => (<span key={tag} className="px-1.5 py-0.5 rounded text-[10px] bg-white/[0.04] text-white/40 border border-white/[0.06]">{tag}</span>))}
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
