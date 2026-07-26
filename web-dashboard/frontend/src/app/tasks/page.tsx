"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { CheckSquare, Plus, Search, Calendar, Flag, User } from "lucide-react";

const tasks = [
  { id: "1", title: "Fix Authentication Bug", description: "Critical bug in auth middleware", status: "in_progress", priority: "urgent", assignee: "Alex Chen", project: "Data Pipeline v2", dueDate: "2024-02-01", tags: ["bug", "critical"] },
  { id: "2", title: "Implement WebSocket Support", description: "Add real-time updates to dashboard", status: "todo", priority: "high", assignee: "Sarah Johnson", project: "AI Model Training", dueDate: "2024-02-05", tags: ["feature", "backend"] },
  { id: "3", title: "Update Documentation", description: "API docs need updating for v2", status: "review", priority: "medium", assignee: "Mike Davis", project: "Customer Portal", dueDate: "2024-02-10", tags: ["docs"] },
  { id: "4", title: "Security Audit Review", description: "Review security audit findings", status: "in_progress", priority: "high", assignee: "Emma Wilson", project: "Security Audit", dueDate: "2024-02-03", tags: ["security", "audit"] },
  { id: "5", title: "Optimize Database Queries", description: "Slow query optimization", status: "done", priority: "medium", assignee: "Chris Lee", project: "Data Pipeline v2", dueDate: "2024-01-20", tags: ["performance"] },
  { id: "6", title: "Design New Dashboard", description: "Create new dashboard mockups", status: "todo", priority: "medium", assignee: "Lisa Park", project: "Customer Portal", dueDate: "2024-02-15", tags: ["design", "ui"] },
];

export default function TasksPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const filteredTasks = tasks.filter((t) => t.title.toLowerCase().includes(searchQuery.toLowerCase()) && (statusFilter === "all" || t.status === statusFilter));

  const getStatusColor = (status: string) => {
    switch (status) {
      case "done": return "bg-green-500/10 text-green-400 border-green-500/20";
      case "in_progress": return "bg-blue-500/10 text-blue-400 border-blue-500/20";
      case "review": return "bg-purple-500/10 text-purple-400 border-purple-500/20";
      case "todo": return "bg-white/10 text-white/40 border-white/20";
      default: return "bg-white/10 text-white/40 border-white/20";
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case "urgent": return "text-red-400";
      case "high": return "text-orange-400";
      case "medium": return "text-blue-400";
      default: return "text-white/40";
    }
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Tasks</h1>
          <p className="text-sm text-white/40 mt-1">Track and manage all tasks</p>
        </div>
        <button className="btn-primary"><Plus className="w-4 h-4" />New Task</button>
      </motion.div>
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
          <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search tasks..." className="w-full pl-10 pr-4 py-2.5 rounded-xl glass-input text-sm text-white placeholder-white/30 outline-none" />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none">
          <option value="all" className="bg-space-800">All Status</option>
          <option value="todo" className="bg-space-800">Todo</option>
          <option value="in_progress" className="bg-space-800">In Progress</option>
          <option value="review" className="bg-space-800">Review</option>
          <option value="done" className="bg-space-800">Done</option>
        </select>
      </motion.div>
      <div className="space-y-3">
        {filteredTasks.map((task, i) => (
          <motion.div key={task.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="glass-card p-4">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-2">
                  <h3 className="text-sm font-semibold text-white">{task.title}</h3>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${getStatusColor(task.status)}`}>{task.status.replace("_", " ")}</span>
                  <Flag className={`w-3.5 h-3.5 ${getPriorityColor(task.priority)}`} />
                </div>
                <p className="text-xs text-white/40 mb-2">{task.description}</p>
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-1.5"><User className="w-3 h-3 text-white/30" /><span className="text-xs text-white/40">{task.assignee}</span></div>
                  <div className="flex items-center gap-1.5"><Calendar className="w-3 h-3 text-white/30" /><span className="text-xs text-white/40">{task.dueDate}</span></div>
                  <div className="flex items-center gap-1">
                    {task.tags.map((tag) => (<span key={tag} className="px-1.5 py-0.5 rounded text-[10px] bg-white/[0.04] text-white/40 border border-white/[0.06]">{tag}</span>))}
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
