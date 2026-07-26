"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Shield, AlertTriangle, Lock, Globe, FileText, Eye, X } from "lucide-react";

const threats = [
  { id: "1", title: "Brute Force Attack", severity: "high", status: "active", sourceIp: "192.168.1.100", target: "auth-api", detectedAt: "2m ago", description: "15 failed login attempts detected" },
  { id: "2", title: "Suspicious API Activity", severity: "medium", status: "investigating", sourceIp: "10.0.0.45", target: "data-api", detectedAt: "15m ago", description: "Unusual data extraction pattern" },
  { id: "3", title: "SSL Certificate Expiring", severity: "medium", status: "active", sourceIp: "-", target: "api.aionex.io", detectedAt: "1h ago", description: "Certificate expires in 7 days" },
];

const events = [
  { id: "1", type: "login", user: "Alex Chen", ip: "192.168.1.50", result: "success", time: "2m ago", risk: 10 },
  { id: "2", type: "failed_login", user: "Unknown", ip: "192.168.1.100", result: "failure", time: "5m ago", risk: 85 },
  { id: "3", type: "api_call", user: "Sarah Johnson", ip: "192.168.1.51", result: "success", time: "10m ago", risk: 15 },
  { id: "4", type: "permission_change", user: "Alex Chen", ip: "192.168.1.50", result: "success", time: "1h ago", risk: 45 },
];

export default function SecurityPage() {
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Security</h1>
          <p className="text-sm text-white/40 mt-1">Monitor threats and security events</p>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="glass-card p-5">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle className="w-4 h-4 text-red-400" />
            <h2 className="text-sm font-semibold text-white">Active Threats</h2>
          </div>
          <div className="space-y-3">
            {threats.map((threat) => (
              <div key={threat.id} className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-white">{threat.title}</span>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${threat.severity === "high" ? "bg-red-500/10 text-red-400 border-red-500/20" : "bg-orange-500/10 text-orange-400 border-orange-500/20"}`}>{threat.severity}</span>
                </div>
                <p className="text-xs text-white/40 mb-2">{threat.description}</p>
                <div className="flex items-center gap-3 text-[10px] text-white/30">
                  <span>Source: {threat.sourceIp}</span>
                  <span>Target: {threat.target}</span>
                  <span>{threat.detectedAt}</span>
                </div>
              </div>
            ))}
          </div>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="glass-card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Eye className="w-4 h-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-white">Recent Security Events</h2>
          </div>
          <div className="space-y-2">
            {events.map((event) => (
              <div key={event.id} className="flex items-center gap-3 py-2 border-b border-white/[0.04] last:border-0">
                <div className={`w-2 h-2 rounded-full ${event.result === "success" ? "bg-green-500" : "bg-red-500"}`} />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-white">{event.type.replace("_", " ").replace(/\b\w/g, (l) => l.toUpperCase())}</span>
                    <span className="text-xs text-white/40">by {event.user}</span>
                  </div>
                  <div className="flex items-center gap-3 text-[10px] text-white/30">
                    <span>IP: {event.ip}</span>
                    <span>Risk: {event.risk}</span>
                    <span>{event.time}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
