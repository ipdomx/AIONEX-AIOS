"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Server, Plus, Search, Cpu, HardDrive, Network, Power, RefreshCw } from "lucide-react";

const servers = [
  { id: "1", name: "prod-web-01", hostname: "prod-web-01.aionex.io", ip: "10.0.1.10", status: "online", os: "Ubuntu 22.04 LTS", cpu: 67.5, memory: 78.2, disk: 45.0, networkRx: 145.2, networkTx: 98.7, uptime: 2592000, location: "Dubai, UAE", provider: "AWS" },
  { id: "2", name: "prod-web-02", hostname: "prod-web-02.aionex.io", ip: "10.0.1.11", status: "online", os: "Ubuntu 22.04 LTS", cpu: 45.2, memory: 62.1, disk: 38.5, networkRx: 125.4, networkTx: 89.2, uptime: 2592000, location: "Dubai, UAE", provider: "AWS" },
  { id: "3", name: "prod-db-01", hostname: "prod-db-01.aionex.io", ip: "10.0.2.10", status: "online", os: "Ubuntu 22.04 LTS", cpu: 82.3, memory: 91.5, disk: 67.8, networkRx: 234.1, networkTx: 156.7, uptime: 5184000, location: "Frankfurt, DE", provider: "Contabo" },
  { id: "4", name: "prod-cache-01", hostname: "prod-cache-01.aionex.io", ip: "10.0.3.10", status: "maintenance", os: "Alpine Linux", cpu: 12.5, memory: 34.2, disk: 23.1, networkRx: 89.3, networkTx: 67.4, uptime: 864000, location: "Dubai, UAE", provider: "AWS" },
  { id: "5", name: "prod-worker-01", hostname: "prod-worker-01.aionex.io", ip: "10.0.4.10", status: "online", os: "Ubuntu 22.04 LTS", cpu: 34.8, memory: 45.6, disk: 28.9, networkRx: 67.2, networkTx: 45.8, uptime: 1728000, location: "Singapore, SG", provider: "AWS" },
  { id: "6", name: "prod-worker-02", hostname: "prod-worker-02.aionex.io", ip: "10.0.4.11", status: "warning", os: "Ubuntu 22.04 LTS", cpu: 89.2, memory: 87.3, disk: 56.4, networkRx: 178.5, networkTx: 123.6, uptime: 1728000, location: "Singapore, SG", provider: "AWS" },
];

export default function ServersPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const filteredServers = servers.filter((s) => s.name.toLowerCase().includes(searchQuery.toLowerCase()));

  const getStatusColor = (status: string) => {
    switch (status) {
      case "online": return "bg-green-500/10 text-green-400 border-green-500/20";
      case "warning": return "bg-orange-500/10 text-orange-400 border-orange-500/20";
      case "maintenance": return "bg-blue-500/10 text-blue-400 border-blue-500/20";
      case "offline": return "bg-red-500/10 text-red-400 border-red-500/20";
      default: return "bg-white/10 text-white/40 border-white/20";
    }
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Servers</h1>
          <p className="text-sm text-white/40 mt-1">Monitor and manage infrastructure servers</p>
        </div>
        <button className="btn-primary"><Plus className="w-4 h-4" />Add Server</button>
      </motion.div>
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
        <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search servers..." className="w-full pl-10 pr-4 py-2.5 rounded-xl glass-input text-sm text-white placeholder-white/30 outline-none" />
      </div>
      <div className="space-y-3">
        {filteredServers.map((server, i) => (
          <motion.div key={server.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="glass-card p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-electric-500/20 to-cyan-500/20 flex items-center justify-center border border-white/[0.08]">
                  <Server className="w-5 h-5 text-electric-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">{server.name}</h3>
                  <p className="text-xs text-white/40">{server.hostname} • {server.ip}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusColor(server.status)}`}>{server.status}</span>
                <button className="p-2 rounded-lg hover:bg-white/[0.06] transition-colors"><Power className="w-4 h-4 text-white/40" /></button>
                <button className="p-2 rounded-lg hover:bg-white/[0.06] transition-colors"><RefreshCw className="w-4 h-4 text-white/40" /></button>
              </div>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="p-2.5 rounded-lg bg-white/[0.02]">
                <div className="flex items-center gap-1.5 mb-1"><Cpu className="w-3 h-3 text-electric-400" /><span className="text-[10px] text-white/40 uppercase tracking-wider">CPU</span></div>
                <span className="text-sm font-bold text-white">{server.cpu}%</span>
              </div>
              <div className="p-2.5 rounded-lg bg-white/[0.02]">
                <div className="flex items-center gap-1.5 mb-1"><HardDrive className="w-3 h-3 text-purple-400" /><span className="text-[10px] text-white/40 uppercase tracking-wider">Memory</span></div>
                <span className="text-sm font-bold text-white">{server.memory}%</span>
              </div>
              <div className="p-2.5 rounded-lg bg-white/[0.02]">
                <div className="flex items-center gap-1.5 mb-1"><HardDrive className="w-3 h-3 text-green-400" /><span className="text-[10px] text-white/40 uppercase tracking-wider">Disk</span></div>
                <span className="text-sm font-bold text-white">{server.disk}%</span>
              </div>
              <div className="p-2.5 rounded-lg bg-white/[0.02]">
                <div className="flex items-center gap-1.5 mb-1"><Network className="w-3 h-3 text-orange-400" /><span className="text-[10px] text-white/40 uppercase tracking-wider">Network</span></div>
                <span className="text-sm font-bold text-white">{server.networkRx} Mbps</span>
              </div>
            </div>
            <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/[0.06]">
              <div className="flex items-center gap-3">
                <span className="text-xs text-white/30">{server.os}</span>
                <span className="text-xs text-white/20">•</span>
                <span className="text-xs text-white/30">{server.location}</span>
                <span className="text-xs text-white/20">•</span>
                <span className="text-xs text-white/30">{server.provider}</span>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
