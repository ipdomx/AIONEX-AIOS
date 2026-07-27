"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Building2, FolderKanban, Play, ShieldCheck, UserCog } from "lucide-react";
import { executeOwnerOperation, type OwnerEntityKind, type OwnerOperation } from "@/lib/owner-operations";

const entities: { value: OwnerEntityKind; label: string }[] = [
  { value: "project", label: "Project" },
  { value: "organization", label: "Organization" },
  { value: "user", label: "User" },
];

const operations: OwnerOperation[] = ["create", "update", "suspend", "restore", "delete"];

export default function OwnerOperationsPage() {
  const [entity, setEntity] = useState<OwnerEntityKind>("project");
  const [operation, setOperation] = useState<OwnerOperation>("update");
  const [recordId, setRecordId] = useState("");
  const [name, setName] = useState("");
  const [message, setMessage] = useState("Owner operations gateway ready.");
  const [running, setRunning] = useState(false);

  const Icon = useMemo(() => entity === "project" ? FolderKanban : entity === "organization" ? Building2 : UserCog, [entity]);

  async function submit() {
    setRunning(true);
    setMessage("Executing protected owner operation...");
    try {
      const result = await executeOwnerOperation({ entity, operation, id: recordId || undefined, payload: name ? { name } : undefined });
      setMessage(`${result.message} Operation ID: ${result.operationId}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Owner operation failed.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><ShieldCheck className="h-3.5 w-3.5" /> Owner CRUD Gateway</div>
        <h1 className="text-3xl font-bold tracking-tight text-white">Protected Entity Operations</h1>
        <p className="mt-2 text-sm text-white/45">Backend-connected create, update, suspend, restore and delete operations for owner-managed records.</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_320px]">
        <div className="glass-card space-y-4 p-5">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="space-y-2 text-xs text-white/50">Entity<select value={entity} onChange={(event) => setEntity(event.target.value as OwnerEntityKind)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none">{entities.map((item) => <option key={item.value} value={item.value} className="bg-space-800">{item.label}</option>)}</select></label>
            <label className="space-y-2 text-xs text-white/50">Operation<select value={operation} onChange={(event) => setOperation(event.target.value as OwnerOperation)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none">{operations.map((item) => <option key={item} value={item} className="bg-space-800">{item}</option>)}</select></label>
          </div>
          <label className="block space-y-2 text-xs text-white/50">Record ID<input value={recordId} onChange={(event) => setRecordId(event.target.value)} placeholder="Optional for create" className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" /></label>
          <label className="block space-y-2 text-xs text-white/50">Name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Payload name" className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" /></label>
          <button disabled={running} onClick={() => void submit()} className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"><Play className="h-4 w-4" />{running ? "Executing..." : "Execute operation"}</button>
          <div className="flex items-start gap-2 rounded-xl border border-electric-500/15 bg-electric-500/5 p-4 text-xs text-electric-300"><Activity className="mt-0.5 h-4 w-4 flex-shrink-0" />{message}</div>
        </div>

        <div className="glass-card p-5"><div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3"><Icon className="h-6 w-6 text-electric-300" /></div><h2 className="mt-4 text-sm font-semibold text-white">Current request</h2><dl className="mt-4 space-y-3 text-xs"><div className="flex justify-between gap-3"><dt className="text-white/35">Entity</dt><dd className="text-white/75">{entity}</dd></div><div className="flex justify-between gap-3"><dt className="text-white/35">Operation</dt><dd className="text-white/75">{operation}</dd></div><div className="flex justify-between gap-3"><dt className="text-white/35">Record</dt><dd className="max-w-[180px] truncate text-white/75">{recordId || "new record"}</dd></div></dl></div>
      </div>
    </div>
  );
}
