"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { AlertCircle, BarChart3, FileText, Loader2 } from "lucide-react";

import { ReportSummary, runtimeServices } from "@/lib/runtime-services";

export default function ReportsPage() {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await runtimeServices.listReports({ limit: 100 });
        if (!cancelled) setReports(data);
      } catch (requestError) {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : "Failed to load reports");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-bold text-white tracking-tight">Reports</h1>
        <p className="text-sm text-white/40 mt-1">Live operational reports from the AIOS runtime</p>
      </motion.div>
      {loading && <div className="glass-card p-8 flex items-center justify-center gap-3 text-white/60"><Loader2 className="w-5 h-5 animate-spin" />Loading reports...</div>}
      {error && <div className="glass-card p-5 border border-red-500/20 flex items-start gap-3 text-red-300"><AlertCircle className="w-5 h-5" /><span>{error}</span></div>}
      {!loading && !error && <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">{reports.map((report, index) => <motion.div key={report.id} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.05 }} className="glass-card p-5"><div className="flex items-start gap-3"><div className="w-10 h-10 rounded-xl bg-purple-500/10 flex items-center justify-center border border-purple-500/20"><FileText className="w-5 h-5 text-purple-400" /></div><div className="flex-1"><div className="flex items-center justify-between"><h2 className="text-sm font-semibold text-white">{report.name}</h2><span className="text-[10px] text-green-400">{report.status}</span></div><p className="text-xs text-white/40 mt-1">{report.type}</p><p className="text-xs text-white/40 mt-4">{report.summary || "No summary"}</p><div className="grid grid-cols-3 gap-2 mt-4">{Object.entries(report.metrics || {}).slice(0, 3).map(([key, value]) => <div key={key} className="rounded-lg bg-white/[0.03] p-3 text-center"><BarChart3 className="w-4 h-4 text-electric-400 mx-auto mb-1" /><div className="text-sm font-semibold text-white">{value}</div><div className="text-[10px] text-white/30">{key.replaceAll("_", " ")}</div></div>)}</div></div></div></motion.div>)}</div>}
    </div>
  );
}
