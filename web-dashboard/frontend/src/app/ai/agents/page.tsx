"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  Bot, Plus, Search, Filter, Play, Pause, Settings,
  CheckCircle2, XCircle, TrendingUp, Clock, Sparkles, Plug,
} from "lucide-react";

const agents = [
  { id: "1", name: "Code Reviewer AI", role: "Code Reviewer", department: "Engineering", status: "running", provider: "OpenAI", model: "gpt-4", tasksCompleted: 892, tasksFailed: 12, performance: 98.7, latency: 145, cost: 124.50, tokensUsed: 2847291 },
  { id: "2", name: "Data Analyzer", role: "Data Analyst", department: "Data Science", status: "running", provider: "Anthropic", model: "claude-3", tasksCompleted: 567, tasksFailed: 8, performance: 97.2, latency: 189, cost: 89.30, tokensUsed: 1245000 },
  { id: "3", name: "Customer Support Bot", role: "Support Agent", department: "Support", status: "idle", provider: "OpenAI", model: "gpt-3.5", tasksCompleted: 2341, tasksFailed: 45, performance: 94.5, latency: 234, cost: 45.20, tokensUsed: 890000 },
  { id: "4", name: "Security Monitor", role: "Security Analyst", department: "Security", status: "running", provider: "OpenRouter", model: "mixtral", tasksCompleted: 1234, tasksFailed: 3, performance: 99.1, latency: 312, cost: 23.10, tokensUsed: 456000 },
  { id: "5", name: "Documentation Writer", role: "Technical Writer", department: "Engineering", status: "paused", provider: "Google", model: "gemini-pro", tasksCompleted: 345, tasksFailed: 15, performance: 92.8, latency: 278, cost: 34.50, tokensUsed: 678000 },
  { id: "6", name: "Test Generator", role: "QA Engineer", department: "QA", status: "running", provider: "OpenAI", model: "gpt-4", tasksCompleted: 678, tasksFailed: 5, performance: 98.9, latency: 167, cost: 78.90, tokensUsed: 1567000 },
];

const providers = [
  { name: "OpenAI", status: "connected", latency: 145 },
  { name: "Anthropic", status: "connected", latency: 189 },
  { name: "Google", status: "connected", latency: 234 },
  { name: "OpenRouter", status: "connected", latency: 312 },
  { name: "Ollama", status: "disconnected", latency: 0 },
];

export default function AIAgentsPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const filteredAgents = agents.filter((agent) => {
    const matchesSearch = agent.name.toLowerCase().includes(searchQuery.toLowerCase()) || agent.role.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === "all" || agent.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getStatusColor = (status: string) => {
    switch (status) {
      case "running": return "bg-green-500/10 text-green-400 border-green-500/20";
      case "idle": return "bg-blue-500/10 text-blue-400 border-blue-500/20";
      case "paused": return "bg-orange-500/10 text-orange-400 border-orange-500/20";
      case "error": return "bg-red-500/10 text-red-400 border-red-500/20";
      default: return "bg-white/10 text-white/40 border-white/20";
    }
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">AI Agents</h1>
          <p className="text-sm text-white/40 mt-1">Manage and monitor your AI workforce</p>
        </div>
        <button className="btn-primary"><Plus className="w-4 h-4" />New Agent</button>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="glass-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Sparkles className="w-4 h-4 text-purple-400" />
          <h2 className="text-sm font-semibold text-white">AI Providers</h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {providers.map((provider) => (
            <div key={provider.name} className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div className="flex items-center gap-2 mb-2">
                <span className={`w-2 h-2 rounded-full ${provider.status === "connected" ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
                <span className="text-xs font-medium text-white">{provider.name}</span>
              </div>
              <div className="text-xs text-white/40">{provider.status === "connected" ? `${provider.latency}ms` : "Offline"}</div>
            </div>
          ))}
        </div>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
          <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search agents..." className="w-full pl-10 pr-4 py-2.5 rounded-xl glass-input text-sm text-white placeholder-white/30 outline-none" />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none">
          <option value="all" className="bg-space-800">All Status</option>
          <option value="running" className="bg-space-800">Running</option>
          <option value="idle" className="bg-space-800">Idle</option>
          <option value="paused" className="bg-space-800">Paused</option>
          <option value="error" className="bg-space-800">Error</option>
        </select>
        <button className="p-2.5 rounded-xl glass hover:bg-white/[0.06] transition-colors"><Filter className="w-4 h-4 text-white/50" /></button>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
        {filteredAgents.map((agent, i) => (
          <motion.div key={agent.id} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.05 }} className="glass-card p-5 group cursor-pointer">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500/20 to-blue-500/20 flex items-center justify-center border border-white/[0.08]">
                  <Bot className="w-5 h-5 text-purple-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">{agent.name}</h3>
                  <p className="text-xs text-white/40">{agent.role} • {agent.department}</p>
                </div>
              </div>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${getStatusColor(agent.status)}`}>{agent.status}</span>
            </div>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <div className="p-2.5 rounded-lg bg-white/[0.02]">
                <div className="flex items-center gap-1.5 mb-1"><CheckCircle2 className="w-3 h-3 text-green-400" /><span className="text-[10px] text-white/40 uppercase tracking-wider">Completed</span></div>
                <span className="text-sm font-bold text-white">{agent.tasksCompleted.toLocaleString()}</span>
              </div>
              <div className="p-2.5 rounded-lg bg-white/[0.02]">
                <div className="flex items-center gap-1.5 mb-1"><XCircle className="w-3 h-3 text-red-400" /><span className="text-[10px] text-white/40 uppercase tracking-wider">Failed</span></div>
                <span className="text-sm font-bold text-white">{agent.tasksFailed}</span>
              </div>
              <div className="p-2.5 rounded-lg bg-white/[0.02]">
                <div className="flex items-center gap-1.5 mb-1"><TrendingUp className="w-3 h-3 text-blue-400" /><span className="text-[10px] text-white/40 uppercase tracking-wider">Performance</span></div>
                <span className="text-sm font-bold text-white">{agent.performance}%</span>
              </div>
              <div className="p-2.5 rounded-lg bg-white/[0.02]">
                <div className="flex items-center gap-1.5 mb-1"><Clock className="w-3 h-3 text-orange-400" /><span className="text-[10px] text-white/40 uppercase tracking-wider">Latency</span></div>
                <span className="text-sm font-bold text-white">{agent.latency}ms</span>
              </div>
            </div>
            <div className="flex items-center justify-between pt-3 border-t border-white/[0.06]">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-white/30">{agent.provider}</span>
                <span className="text-[10px] text-white/20">•</span>
                <span className="text-[10px] text-white/30">{agent.model}</span>
              </div>
              <div className="flex items-center gap-1">
                <button className="p-1.5 rounded-lg hover:bg-white/[0.06] transition-colors"><Play className="w-3.5 h-3.5 text-white/40" /></button>
                <button className="p-1.5 rounded-lg hover:bg-white/[0.06] transition-colors"><Pause className="w-3.5 h-3.5 text-white/40" /></button>
                <button className="p-1.5 rounded-lg hover:bg-white/[0.06] transition-colors"><Settings className="w-3.5 h-3.5 text-white/40" /></button>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
