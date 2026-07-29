"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import {
  BadgeCheck,
  CircleAlert,
  FileCheck2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import {
  attestComplianceControl,
  fetchComplianceControls,
  type ComplianceControl,
} from "@/lib/owner-compliance-runtime";

const statusClass: Record<ComplianceControl["status"], string> = {
  compliant: "border-green-500/20 bg-green-500/10 text-green-300",
  warning: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  noncompliant: "border-red-500/20 bg-red-500/10 text-red-300",
};

type SummaryCard = readonly [label: string, value: number, icon: LucideIcon];

export default function OwnerComplianceRuntimePage() {
  const [items, setItems] = useState<ComplianceControl[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading compliance controls...");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchComplianceControls(signal);
      setItems(data);
      setMessage("Compliance controls synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        setMessage("Compliance synchronization failed.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  const summary = useMemo(
    () => ({
      compliant: items.filter((item) => item.status === "compliant").length,
      warning: items.filter((item) => item.status === "warning").length,
      noncompliant: items.filter((item) => item.status === "noncompliant")
        .length,
    }),
    [items],
  );

  const cards: SummaryCard[] = [
    ["Compliant", summary.compliant, ShieldCheck],
    ["Warnings", summary.warning, CircleAlert],
    ["Non-compliant", summary.noncompliant, FileCheck2],
  ];

  async function attest(id: string) {
    setMessage("Submitting owner attestation...");
    try {
      const attested = await attestComplianceControl(id);
      setItems((current) =>
        current.map((item) => (item.id === id ? attested : item)),
      );
      setMessage("Owner attestation completed.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Owner attestation failed.",
      );
    }
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
            <FileCheck2 className="h-3.5 w-3.5" /> Owner Compliance Runtime
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Compliance Controls & Evidence
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Owner-level control assurance for ISO 27001, SOC 2, GDPR and
            internal governance frameworks.
          </p>
        </div>
        <button
          disabled={loading}
          onClick={() => void load()}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {cards.map(([label, value, Icon]) => (
          <div key={label} className="glass-card p-5">
            <Icon className="h-5 w-5 text-electric-300" />
            <div className="mt-4 text-3xl font-bold text-white">{value}</div>
            <div className="mt-1 text-xs text-white/40">{label}</div>
          </div>
        ))}
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {items.map((item, index) => (
          <motion.div
            key={item.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03 }}
            className="glass-card p-5"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-sm font-semibold text-white">
                  {item.framework} · {item.control}
                </h2>
                <p className="mt-1 text-xs text-white/40">
                  Owner: {item.owner} · Evidence: {item.evidence} ·{" "}
                  {item.updatedAt}
                </p>
              </div>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[item.status]}`}
              >
                {item.status}
              </span>
            </div>
            <button
              onClick={() => void attest(item.id)}
              className="mt-4 rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300"
            >
              <BadgeCheck className="mr-1 inline h-3.5 w-3.5" />
              Attest control
            </button>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
