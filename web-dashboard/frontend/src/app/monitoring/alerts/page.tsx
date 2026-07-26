"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Bell, CheckCircle2, AlertTriangle, Info, XCircle, Clock } from "lucide-react";

const alerts = [
  { id: "1", title: "High CPU Usage", description: "Server prod-web-01 CPU usage exceeded 85%", severity: "warning", status: "active", source: "monitoring", createdAt: "5m ago" },
  { id: "2", title: "Database Connection Failed", description: "PostgreSQL primary connection timeout after 30s", severity: "critical", status: "active", source: "db-monitor", createdAt: "12m ago" },
  { id: "3", title: "SSL Certificate Expiring", description: "Certificate for api.aionex.io expires in 7 days", severity: "warning", status: "active", source: "security", createdAt: "1h ago" },
  { id: "4", title: "Memory Leak Detected", description: "Worker process memory usage growing continuously", severity: "warning", status: "acknowledged", source: "monitoring", createdAt: "2h ago" },
  { id: "5", title: "Deployment Complete", description: "Workflow deployed successfully", severity: "info", status: "resolved", source: "deployment", createdAt: "3h ago" },
];

export default function AlertsPage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const filteredAlerts = alerts.filter((a) => statusFilter === "all" || a.status === statusFilter);

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case "critical": return "bg-red-500/10 text-red-400 border-red-500/20";
      case "warning": return "bg-orange-500/10 text-orange-400 border-orange-500/20";
      case "info": return "bg-blue-500/10 text-blue-400 border-blue-500/20";
      default: return "bg-white/10 text-white/40 border-white/20";
    }
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Alerts</h1>
          <p className="text-sm text-white/40 mt-1">Monitor and manage system alerts</p>
        </div>
      </motion.div>
      <div className="flex items-center gap-3">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none">
          <option value="all" className="bg-space-800">All Status</option>
          <option value="active" className="bg-space-800">Active</option>
          <option value="acknowledged" className="bg-space-800">Acknowledged</option>
          <option value="resolved" className="bg-space-800">Resolved</option>
        </select>
      </div>
      <div className="space-y-3">
        {filteredAlerts.map((alert, i) => (
          <motion.div key={alert.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="glass-card p-4">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-2">
                  <h3 className="text-sm font-semibold text-white">{alert.title}</h3>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${getSeverityColor(alert.severity)}`}>{alert.severity}</span>
                  <span className="px-2 py-0.5 rounded-full text-[10px] bg-white/[0.06] text-white/50 border border-white/[0.08]">{alert.status}</span>
                </div>
                <p className="text-xs text-white/40 mb-2">{alert.description}</p>
                <div className="flex items-center gap-3 text-[10px] text-white/30">
                  <span>Source: {alert.source}</span>
                  <span>{alert.createdAt}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {alert.status === "active" && (
                  <>
                    <button className="px-3 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] text-xs text-white/60 transition-colors">Acknowledge</button>
                    <button className="px-3 py-1.5 rounded-lg bg-green-500/10 hover:bg-green-500/20 text-xs text-green-400 transition-colors">Resolve</button>
                  </>
                )}
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
