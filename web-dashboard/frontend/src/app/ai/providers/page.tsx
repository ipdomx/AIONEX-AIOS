"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Plus, Search, Plug, Settings, RefreshCw } from "lucide-react";

const providers = [
  { id: "1", name: "OpenAI", type: "openai", status: "connected", latency: 145, costPer1k: 0.03, usageToday: 2847291, usageLimit: 10000000, models: 8 },
  { id: "2", name: "Anthropic", type: "anthropic", status: "connected", latency: 189, costPer1k: 0.008, usageToday: 1245000, usageLimit: 5000000, models: 4 },
  { id: "3", name: "Google Gemini", type: "google", status: "connected", latency: 234, costPer1k: 0.001, usageToday: 890000, usageLimit: 5000000, models: 6 },
  { id: "4", name: "OpenRouter", type: "openrouter", status: "connected", latency: 312, costPer1k: 0.005, usageToday: 456000, usageLimit: 2000000, models: 45 },
  { id: "5", name: "Ollama", type: "ollama", status: "disconnected", latency: 0, costPer1k: 0, usageToday: 0, usageLimit: 0, models: 0 },
];

export default function AIProvidersPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const filteredProviders = providers.filter((p) => p.name.toLowerCase().includes(searchQuery.toLowerCase()));

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">AI Providers</h1>
          <p className="text-sm text-white/40 mt-1">Manage AI model providers and monitor usage</p>
        </div>
        <button className="btn-primary"><Plus className="w-4 h-4" />Add Provider</button>
      </motion.div>
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
        <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search providers..." className="w-full pl-10 pr-4 py-2.5 rounded-xl glass-input text-sm text-white placeholder-white/30 outline-none" />
      </div>
      <div className="space-y-3">
        {filteredProviders.map((provider, i) => (
          <motion.div key={provider.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="glass-card p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${provider.status === "connected" ? "bg-green-500/20" : "bg-red-500/20"}`}>
                  <Plug className={`w-5 h-5 ${provider.status === "connected" ? "text-green-400" : "text-red-400"}`} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">{provider.name}</h3>
                  <p className="text-xs text-white/40 capitalize">{provider.type}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`px-2.5 py-1 rounded-full text-xs font-medium border ${provider.status === "connected" ? "bg-green-500/10 text-green-400 border-green-500/20" : "bg-red-500/10 text-red-400 border-red-500/20"}`}>{provider.status}</span>
                <button className="p-2 rounded-lg hover:bg-white/[0.06] transition-colors"><Settings className="w-4 h-4 text-white/40" /></button>
                <button className="p-2 rounded-lg hover:bg-white/[0.06] transition-colors"><RefreshCw className="w-4 h-4 text-white/40" /></button>
              </div>
            </div>
            {provider.status === "connected" && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4 pt-4 border-t border-white/[0.06]">
                <div><div className="text-[10px] text-white/40 uppercase tracking-wider mb-1">Latency</div><div className="text-sm font-bold text-white">{provider.latency}ms</div></div>
                <div><div className="text-[10px] text-white/40 uppercase tracking-wider mb-1">Cost / 1K</div><div className="text-sm font-bold text-white">${provider.costPer1k}</div></div>
                <div><div className="text-[10px] text-white/40 uppercase tracking-wider mb-1">Usage Today</div><div className="text-sm font-bold text-white">{provider.usageToday.toLocaleString()}</div></div>
                <div><div className="text-[10px] text-white/40 uppercase tracking-wider mb-1">Models</div><div className="text-sm font-bold text-white">{provider.models}</div></div>
              </div>
            )}
          </motion.div>
        ))}
      </div>
    </div>
  );
}
