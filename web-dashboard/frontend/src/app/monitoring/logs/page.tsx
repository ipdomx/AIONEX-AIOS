"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { FileText, Search, Filter, Download, AlertCircle, Info, AlertTriangle, XCircle } from "lucide-react";

const logs = [
  { id: "1", timestamp: "2024-01-15T10:00:00Z", level: "info", service: "api", message: "Request processed successfully", traceId: "trace-123" },
  { id: "2", timestamp: "2024-01-15T10:01:00Z", level: "warning", service: "worker", message: "Queue depth exceeding threshold", traceId: "trace-124" },
  { id: "3", timestamp: "2024-01-15T10:02:00Z", level: "error", service: "db", message: "Connection timeout after 30s", traceId: "trace-125" },
  { id: "4", timestamp: "2024-01-15T10:03:00Z", level: "info", service: "api", message: "User authenticated successfully", traceId: "trace-126" },
  { id: "5", timestamp: "2024-01-15T10:04:00Z", level: "debug", service: "agent", message: "Agent processing task #1234", traceId: "trace-127" },
  { id: "6", timestamp: "2024-01-15T10:05:00Z", level: "error", service: "api", message: "Rate limit exceeded for IP 192.168.1.100", traceId: "trace-128" },
];

export default function LogsPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [levelFilter, setLevelFilter] = useState("all");
  const filteredLogs = logs.filter((l) => l.message.toLowerCase().includes(searchQuery.toLowerCase()) && (levelFilter === "all" || l.level === levelFilter));

  const getLevelIcon = (level: string) => {
    switch (level) {
      case "error": return <XCircle className="w-4 h-4 text-red-400" />;
      case "warning": return <AlertTriangle className="w-4 h-4 text-orange-400" />;
      case "info": return <Info className="w-4 h-4 text-blue-400" />;
      default: return <FileText className="w-4 h-4 text-white/30" />;
    }
  };

  const getLevelColor = (level: string) => {
    switch (level) {
      case "error": return "bg-red-500/10 text-red-400 border-red-500/20";
      case "warning": return "bg-orange-500/10 text-orange-400 border-orange-500/20";
      case "info": return "bg-blue-500/10 text-blue-400 border-blue-500/20";
      default: return "bg-white/10 text-white/40 border-white/20";
    }
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Logs</h1>
          <p className="text-sm text-white/40 mt-1">System logs and events</p>
        </div>
        <button className="btn-secondary"><Download className="w-4 h-4" />Export</button>
      </motion.div>
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
          <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search logs..." className="w-full pl-10 pr-4 py-2.5 rounded-xl glass-input text-sm text-white placeholder-white/30 outline-none" />
        </div>
        <select value={levelFilter} onChange={(e) => setLevelFilter(e.target.value)} className="px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none">
          <option value="all" className="bg-space-800">All Levels</option>
          <option value="debug" className="bg-space-800">Debug</option>
          <option value="info" className="bg-space-800">Info</option>
          <option value="warning" className="bg-space-800">Warning</option>
          <option value="error" className="bg-space-800">Error</option>
        </select>
      </div>
      <div className="glass-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead><tr className="border-b border-white/[0.06]"><th className="text-left px-4 py-3 text-xs font-semibold text-white/40 uppercase tracking-wider">Level</th><th className="text-left px-4 py-3 text-xs font-semibold text-white/40 uppercase tracking-wider">Time</th><th className="text-left px-4 py-3 text-xs font-semibold text-white/40 uppercase tracking-wider">Service</th><th className="text-left px-4 py-3 text-xs font-semibold text-white/40 uppercase tracking-wider">Message</th><th className="text-left px-4 py-3 text-xs font-semibold text-white/40 uppercase tracking-wider">Trace ID</th></tr></thead>
            <tbody>
              {filteredLogs.map((log, i) => (
                <motion.tr key={log.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.03 }} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                  <td className="px-4 py-3"><span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${getLevelColor(log.level)}`}>{log.level}</span></td>
                  <td className="px-4 py-3 text-xs text-white/40 font-mono">{log.timestamp}</td>
                  <td className="px-4 py-3 text-xs text-white/60">{log.service}</td>
                  <td className="px-4 py-3 text-sm text-white/70">{log.message}</td>
                  <td className="px-4 py-3 text-xs text-white/30 font-mono">{log.traceId}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
