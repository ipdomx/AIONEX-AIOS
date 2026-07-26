"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { AlertCircle, Loader2, Play, Workflow } from "lucide-react";

import { runtimeServices, WorkflowSummary } from "@/lib/runtime-services";

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await runtimeServices.listWorkflows({ limit: 100 });
        if (!cancelled) setWorkflows(data);
      } catch (requestError) {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : "Failed to load workflows");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  async function runWorkflow(workflowId: string) {
    try {
      setRunning(workflowId);
      await runtimeServices.runWorkflow(workflowId);
      const data = await runtimeServices.listWorkflows({ limit: 100 });
      setWorkflows(data);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to run workflow");
    } finally {
      setRunning(null);
    }
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-bold text-white tracking-tight">Workflows</h1>
        <p className="text-sm text-white/40 mt-1">Live governed workflows from the AIOS runtime</p>
      </motion.div>
      {loading && <div className="glass-card p-8 flex items-center justify-center gap-3 text-white/60"><Loader2 className="w-5 h-5 animate-spin" />Loading workflows...</div>}
      {error && <div className="glass-card p-5 border border-red-500/20 flex items-start gap-3 text-red-300"><AlertCircle className="w-5 h-5" /><span>{error}</span></div>}
      {!loading && !error && <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">{workflows.map((workflowItem, index) => <motion.div key={workflowItem.id} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.05 }} className="glass-card p-5"><div className="flex items-start justify-between gap-4"><div><div className="flex items-center gap-3"><div className="w-10 h-10 rounded-xl bg-electric-500/10 flex items-center justify-center border border-electric-500/20"><Workflow className="w-5 h-5 text-electric-400" /></div><div><h2 className="text-sm font-semibold text-white">{workflowItem.name}</h2><p className="text-xs text-white/40">{workflowItem.trigger} trigger · {workflowItem.status}</p></div></div><p className="text-xs text-white/40 mt-4">{workflowItem.description || "No description"}</p><div className="flex items-center gap-4 mt-4 text-xs text-white/30"><span>{workflowItem.steps.length} steps</span><span>{workflowItem.run_count} runs</span><span>{workflowItem.last_run_at || "Never run"}</span></div></div><button disabled={running === workflowItem.id} onClick={() => void runWorkflow(workflowItem.id)} className="btn-primary"><Play className="w-4 h-4" />{running === workflowItem.id ? "Running" : "Run"}</button></div></motion.div>)}</div>}
    </div>
  );
}
