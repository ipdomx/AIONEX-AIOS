"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
  recordComplianceEvidence,
  type ComplianceControl,
} from "@/lib/owner-compliance-runtime";

const statusClass: Record<ComplianceControl["status"], string> = {
  compliant: "border-green-500/20 bg-green-500/10 text-green-300",
  partial: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  warning: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  non_compliant: "border-red-500/20 bg-red-500/10 text-red-300",
  not_applicable: "border-white/10 bg-white/[0.03] text-white/40",
  not_assessed: "border-white/10 bg-white/[0.03] text-white/40",
};

type SummaryCard = readonly [label: string, value: number, icon: LucideIcon];

export default function OwnerComplianceRuntimePage() {
  const [items, setItems] = useState<ComplianceControl[]>([]);
  const [loading, setLoading] = useState(true);
  const [actingId, setActingId] = useState<string | null>(null);
  const [evidenceReferences, setEvidenceReferences] = useState<
    Record<string, string>
  >({});
  const [message, setMessage] = useState("Loading compliance controls...");
  const actionInFlight = useRef(false);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchComplianceControls(signal);
      setItems(data);
      setMessage("Compliance controls synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setItems([]);
        setMessage("Compliance backend contract is not available.");
      }
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
      warning: items.filter((item) =>
        ["warning", "partial"].includes(item.status),
      ).length,
      noncompliant: items.filter((item) => item.status === "non_compliant")
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
    if (actionInFlight.current) return;
    const control = items.find((item) => item.id === id);
    if (!control || control.evidence <= 0) return;
    actionInFlight.current = true;
    setActingId(id);
    setMessage("Submitting owner attestation...");
    try {
      const attested = await attestComplianceControl(id);
      setItems((current) =>
        current.map((item) => (item.id === id ? attested : item)),
      );
      setMessage("Owner attestation completed.");
    } catch {
      setMessage("Attestation failed and was not persisted.");
    } finally {
      actionInFlight.current = false;
      setActingId(null);
    }
  }

  async function recordEvidence(id: string) {
    const reference = evidenceReferences[id]?.trim() ?? "";
    if (!reference || actionInFlight.current) return;
    actionInFlight.current = true;
    setActingId(id);
    setMessage("Recording compliance evidence reference...");
    try {
      await recordComplianceEvidence(id, reference);
      setEvidenceReferences((current) => ({ ...current, [id]: "" }));
      await load();
      setMessage("Evidence reference recorded and controls reloaded.");
    } catch {
      setMessage("Evidence reference was not recorded.");
    } finally {
      actionInFlight.current = false;
      setActingId(null);
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
            Evidence-backed Owner attestations for ISO 27001, SOC 2, GDPR and
            internal governance frameworks.
          </p>
        </div>
        <button
          disabled={loading || actingId !== null}
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
            <div className="mt-4 flex flex-col gap-2 sm:flex-row">
              <label className="min-w-0 flex-1">
                <span className="sr-only">
                  Evidence reference for {item.control}
                </span>
                <input
                  value={evidenceReferences[item.id] ?? ""}
                  onChange={(event) =>
                    setEvidenceReferences((current) => ({
                      ...current,
                      [item.id]: event.target.value,
                    }))
                  }
                  placeholder="Evidence reference, URL, ticket, or artifact ID"
                  className="glass-input w-full rounded-lg px-3 py-2 text-xs text-white outline-none"
                />
              </label>
              <button
                disabled={
                  actingId !== null || !evidenceReferences[item.id]?.trim()
                }
                onClick={() => void recordEvidence(item.id)}
                className="rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-300 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {actingId === item.id ? "Recording…" : "Record evidence"}
              </button>
            </div>
            <button
              disabled={actingId !== null || item.evidence <= 0}
              onClick={() => void attest(item.id)}
              className="mt-4 rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <BadgeCheck className="mr-1 inline h-3.5 w-3.5" />
              {item.evidence > 0 ? "Attest control" : "Evidence required"}
            </button>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
