"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { AlertCircle, Calendar, CheckSquare, Flag, Loader2, Plus, Search, User } from "lucide-react";

import { runtimeServices, TaskSummary } from "@/lib/runtime-services";

export default function TasksPage() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setLoading(true);
        const data = await runtimeServices.listTasks({ limit: 100 });
        if (!cancelled) setTasks(data);
      } catch (requestError) {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : "Failed to load tasks");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  const filteredTasks = useMemo(
    () => tasks.filter((task) => task.title.toLowerCase().includes(searchQuery.toLowerCase()) && (statusFilter === "all" || task.status === statusFilter)),
    [tasks, searchQuery, statusFilter],
  );

  const getStatusColor = (status: string) => {
    switch (status) {
      case "done": return "bg-green-500/10 text-green-400 border-green-500/20";
      case "in_progress": return "bg-blue-500/10 text-blue-400 border-blue-500/20";
      case "review": return "bg-purple-500/10 text-purple-400 border-purple-500/20";
      default: return "bg-white/10 text-white/40 border-white/20";
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case "urgent": return "text-red-400";
      case "critical": return "text-red-400";
      case "high": return "text-orange-400";
      case "medium": return "text-blue-400";
      default: return "text-white/40";
    }
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold text-white tracking-tight">Tasks</h1><p className="text-sm text-white/40 mt-1">Live tasks from the AIOS runtime</p></div>
        <button className="btn-primary"><Plus className="w-4 h-4" />New Task</button>
      </motion.div>
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md"><Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" /><input type="text" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search tasks..." className="w-full pl-10 pr-4 py-2.5 rounded-xl glass-input text-sm text-white placeholder-white/30 outline-none" /></div>
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none"><option value="all" className="bg-space-800">All Status</option><option value="todo" className="bg-space-800">Todo</option><option value="in_progress" className="bg-space-800">In Progress</option><option value="review" className="bg-space-800">Review</option><option value="done" className="bg-space-800">Done</option></select>
      </motion.div>
      {loading && <div className="glass-card p-8 flex items-center justify-center gap-3 text-white/60"><Loader2 className="w-5 h-5 animate-spin" />Loading tasks...</div>}
      {error && <div className="glass-card p-5 border border-red-500/20 flex items-start gap-3 text-red-300"><AlertCircle className="w-5 h-5" /><span>{error}</span></div>}
      {!loading && !error && <div className="space-y-3">{filteredTasks.map((task, index) => <motion.div key={task.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.05 }} className="glass-card p-4"><div className="flex items-start justify-between"><div className="flex-1"><div className="flex items-center gap-3 mb-2"><CheckSquare className="w-4 h-4 text-blue-400" /><h3 className="text-sm font-semibold text-white">{task.title}</h3><span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${getStatusColor(task.status)}`}>{task.status.replace("_", " ")}</span><Flag className={`w-3.5 h-3.5 ${getPriorityColor(task.priority)}`} /></div><div className="flex items-center gap-4"><div className="flex items-center gap-1.5"><User className="w-3 h-3 text-white/30" /><span className="text-xs text-white/40">{task.assignee || "Unassigned"}</span></div><div className="flex items-center gap-1.5"><Calendar className="w-3 h-3 text-white/30" /><span className="text-xs text-white/40">{task.due_date || "No due date"}</span></div><span className="text-xs text-white/30">{task.project || "No project"}</span></div></div></div></motion.div>)}</div>}
    </div>
  );
}
