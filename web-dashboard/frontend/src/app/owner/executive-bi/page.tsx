"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, BarChart3, RefreshCw, ShieldCheck, TrendingUp } from "lucide-react";
import { fetchOwnerExecutiveSnapshot, type OwnerExecutiveSnapshot } from "@/lib/owner-executive-bi";

const emptySnapshot: OwnerExecutiveSnapshot = {
  generatedAt: "",
  metrics: [],
  insights: [],
};

const statusClass = {
  good: "border-green-500/20 bg-green-500/10 text-green-300",
  watch: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  critical: "border-red-500/20 bg-red-500/10 text-red-300",
};

export default function OwnerExecutiveBIPage() {
  const [snapshot, setSnapshot] = useState(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading executive intelligence...");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchOwnerExecutiveSnapshot(signal);
      setSnapshot(data);
      setMessage(`Executive intelligence synchronized at ${new Date(data.generatedAt).toLocaleTimeString()}.`);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) setMessage("Executive intelligence refresh failed.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><BarChart3 className="h-3.5 w-3.5" /> Owner Executive BI</div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Executive Intelligence Center</h1>
          <p className="mt-2 text-sm text-white/45">Owner-only business, operational, financial and risk intelligence with decision-ready recommendations.</p>
        </div>
        <button disabled={loading} onClick={() => void load()} className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />Refresh</button>
      </motion.div>

      <div className="glass-card p-4 text-xs text-electric-300"><Activity className="mr-2 inline h-3.5 w-3.5" />{message}</div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {snapshot.metrics.map((metric) => (
          <div key={metric.id} className="glass-card p-5">
            <div className="flex items-start justify-between gap-3"><TrendingUp className="h-5 w-5 text-electric-300" /><span className={`rounded-full border px-2 py-1 text-[10px] ${statusClass[metric.status]}`}>{metric.status}</span></div>
            <div className="mt-4 text-2xl font-bold text-white">{metric.value.toLocaleString()} <span className="text-sm font-medium text-white/35">{metric.unit}</span></div>
            <div className="mt-1 text-xs text-white/40">{metric.label}</div>
            <div className={`mt-3 text-xs ${metric.trend >= 0 ? "text-green-300" : "text-orange-300"}`}>{metric.trend >= 0 ? "+" : ""}{metric.trend}% trend</div>
          </div>
        ))}
      </div>

      <section className="space-y-3">
        <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-electric-300" /><h2 className="text-sm font-semibold text-white">Decision intelligence</h2></div>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {snapshot.insights.map((insight) => (
            <div key={insight.id} className="glass-card p-5">
              <div className="flex items-start justify-between gap-4"><div><h3 className="text-sm font-semibold text-white">{insight.title}</h3><p className="mt-2 text-xs leading-5 text-white/45">{insight.summary}</p></div><AlertTriangle className={`h-5 w-5 ${insight.severity === "critical" ? "text-red-300" : insight.severity === "warning" ? "text-orange-300" : "text-electric-300"}`} /></div>
              <div className="mt-4 rounded-xl border border-white/[0.06] bg-white/[0.03] p-4 text-xs text-white/60"><span className="font-semibold text-white">Recommendation:</span> {insight.recommendation}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
