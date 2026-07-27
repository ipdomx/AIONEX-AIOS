"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ClipboardCheck, FileCheck2, Search, ShieldCheck, XCircle } from "lucide-react";

type Framework = "ISO 27001" | "SOC 2" | "GDPR" | "NIST";
type ControlStatus = "compliant" | "partial" | "non_compliant" | "not_applicable";

type ComplianceControl = {
  id: string;
  framework: Framework;
  control: string;
  owner: string;
  evidence: string;
  status: ControlStatus;
  risk: "low" | "medium" | "high" | "critical";
};

const initialControls: ComplianceControl[] = [
  { id: "iso-a5", framework: "ISO 27001", control: "Information security policies", owner: "Security", evidence: "Policy repository", status: "compliant", risk: "low" },
  { id: "soc-cc6", framework: "SOC 2", control: "Logical access controls", owner: "Platform", evidence: "RBAC audit trail", status: "partial", risk: "high" },
  { id: "gdpr-30", framework: "GDPR", control: "Records of processing activities", owner: "Legal", evidence: "Data inventory", status: "compliant", risk: "medium" },
  { id: "nist-idam", framework: "NIST", control: "Identity and access management", owner: "Security", evidence: "Access review", status: "non_compliant", risk: "critical" },
  { id: "soc-cc7", framework: "SOC 2", control: "Incident detection and response", owner: "Operations", evidence: "Incident runbooks", status: "partial", risk: "medium" },
  { id: "gdpr-32", framework: "GDPR", control: "Security of processing", owner: "Infrastructure", evidence: "Encryption controls", status: "compliant", risk: "low" },
];

const statusClass: Record<ControlStatus, string> = {
  compliant: "border-green-500/20 bg-green-500/10 text-green-400",
  partial: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  non_compliant: "border-red-500/20 bg-red-500/10 text-red-400",
  not_applicable: "border-white/10 bg-white/[0.03] text-white/35",
};

const riskClass: Record<ComplianceControl["risk"], string> = {
  low: "text-green-400",
  medium: "text-blue-300",
  high: "text-orange-400",
  critical: "text-red-400",
};

export default function OwnerCompliancePage() {
  const [controls, setControls] = useState(initialControls);
  const [framework, setFramework] = useState<"all" | Framework>("all");
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("Compliance evidence synchronized.");

  const visible = useMemo(() => controls.filter((item) => {
    const matchesFramework = framework === "all" || item.framework === framework;
    const needle = query.toLowerCase();
    const matchesQuery = item.control.toLowerCase().includes(needle) || item.owner.toLowerCase().includes(needle) || item.evidence.toLowerCase().includes(needle);
    return matchesFramework && matchesQuery;
  }), [controls, framework, query]);

  function updateStatus(id: string, status: ControlStatus) {
    setControls((items) => items.map((item) => item.id === id ? { ...item, status } : item));
    setMessage(`Compliance control updated: ${id} → ${status}.`);
  }

  function runAssessment() {
    setControls((items) => items.map((item) => item.status === "non_compliant" ? { ...item, status: "partial" } : item));
    setMessage("Owner compliance assessment completed and remediation state refreshed.");
  }

  const compliant = controls.filter((item) => item.status === "compliant").length;
  const partial = controls.filter((item) => item.status === "partial").length;
  const nonCompliant = controls.filter((item) => item.status === "non_compliant").length;
  const score = Math.round(((compliant + partial * 0.5) / controls.length) * 100);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300"><ShieldCheck className="h-3.5 w-3.5" /> Owner Compliance Center</div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Compliance & Assurance</h1>
          <p className="mt-2 text-sm text-white/45">Owner visibility across ISO 27001, SOC 2, GDPR and NIST controls, evidence, risk and remediation.</p>
        </div>
        <button onClick={runAssessment} className="btn-primary"><ClipboardCheck className="h-4 w-4" />Run assessment</button>
      </motion.div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {[
          ["Compliance Score", `${score}%`, ShieldCheck],
          ["Compliant", compliant, CheckCircle2],
          ["Partial", partial, AlertTriangle],
          ["Non-Compliant", nonCompliant, XCircle],
          ["Evidence Items", controls.length, FileCheck2],
        ].map(([label, value, Icon]) => {
          const MetricIcon = Icon as typeof ShieldCheck;
          return <div key={String(label)} className="glass-card p-4"><MetricIcon className="h-5 w-5 text-electric-300" /><div className="mt-3 text-2xl font-bold text-white">{String(value)}</div><div className="text-xs text-white/35">{String(label)}</div></div>;
        })}
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full max-w-xl"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search controls, owners or evidence..." className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none" /></div>
          <select value={framework} onChange={(event) => setFramework(event.target.value as typeof framework)} className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none">
            <option value="all" className="bg-space-800">All frameworks</option>
            <option value="ISO 27001" className="bg-space-800">ISO 27001</option>
            <option value="SOC 2" className="bg-space-800">SOC 2</option>
            <option value="GDPR" className="bg-space-800">GDPR</option>
            <option value="NIST" className="bg-space-800">NIST</option>
          </select>
        </div>
        <div className="mt-3 text-xs text-electric-300">{message}</div>
      </div>

      <div className="space-y-3">
        {visible.map((item, index) => (
          <motion.div key={item.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }} className="glass-card p-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex items-start gap-3"><div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5"><FileCheck2 className="h-5 w-5 text-electric-300" /></div><div><h2 className="text-sm font-semibold text-white">{item.control}</h2><p className="mt-1 text-xs text-white/40">{item.framework} · Owner: {item.owner}</p><p className="mt-2 text-xs text-white/35">Evidence: {item.evidence}</p><p className={`mt-2 text-xs font-medium ${riskClass[item.risk]}`}>Risk: {item.risk}</p></div></div>
              <div className="flex flex-wrap items-center gap-2"><span className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[item.status]}`}>{item.status.replace("_", " ")}</span><button onClick={() => updateStatus(item.id, "compliant")} className="rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300">Compliant</button><button onClick={() => updateStatus(item.id, "partial")} className="rounded-lg border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300">Partial</button><button onClick={() => updateStatus(item.id, "non_compliant")} className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">Fail</button></div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
