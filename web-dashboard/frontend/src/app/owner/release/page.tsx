"use client";

import { motion } from "framer-motion";
import {
  CheckCircle2,
  CircleDashed,
  PackageCheck,
  Rocket,
  ShieldCheck,
  TestTube2,
  XCircle,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type ReleaseGateStatus = "passed" | "pending" | "blocked" | "rejected";

type ReleaseGate = {
  id: string;
  name: string;
  owner: string;
  status: ReleaseGateStatus;
  enabled: boolean;
  version: number;
  updatedAt: string;
  lastResult?: string;
};

const gateStatusClass: Record<ReleaseGateStatus, string> = {
  passed: "bg-green-500/10 text-green-400",
  pending: "bg-orange-500/10 text-orange-300",
  blocked: "bg-red-500/10 text-red-300",
  rejected: "bg-red-500/10 text-red-300",
};

export default function OwnerReleasePage() {
  const { items, loading, busy, message, execute } =
    useOwnerResource<ReleaseGate>("release");
  const approvalGate = items.find((gate) => gate.id === "approval");
  const validationGates = items.filter((gate) => gate.id !== "approval");
  const checksPassed = validationGates.filter(
    (gate) => gate.status === "passed",
  ).length;
  const checksReady =
    validationGates.length > 0 && checksPassed === validationGates.length;
  const releaseApproved = approvalGate?.status === "passed";
  const releaseReady =
    items.length > 0 && items.every((gate) => gate.status === "passed");

  function validateGate(gate: ReleaseGate) {
    if (
      gate.id === "approval" &&
      !window.confirm(
        "Approve this release after all live validation gates have passed?",
      )
    ) {
      return;
    }
    void execute(gate.id, gate.id === "approval" ? "approve" : "validate");
  }

  function approveRelease() {
    if (approvalGate) validateGate(approvalGate);
  }

  const securityGate = items.find((gate) => gate.id === "security");
  const backupGate = items.find((gate) => gate.id === "backup");

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <Rocket className="h-3.5 w-3.5" />
            Owner Release Authority
          </div>
          <h1 className="text-3xl font-bold text-white">
            Release Readiness &amp; Final Approval
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Live runtime evidence and Owner authorization for release. CodeQL,
            build, and test results remain authoritative in the external
            workflow and are never inferred from these runtime checks.
          </p>
        </div>
        <button
          onClick={approveRelease}
          disabled={
            loading || busy || !approvalGate || !checksReady || releaseApproved
          }
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <ShieldCheck className="h-4 w-4" />
          {releaseApproved
            ? "Release Approved"
            : checksReady
              ? "Approve Release"
              : "Complete validation gates"}
        </button>
      </motion.div>

      <div className="text-xs text-electric-300">
        {loading ? "Loading release gates..." : message}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {[
          {
            label: "Validation suites",
            value: `${checksPassed}/${validationGates.length}`,
            icon: TestTube2,
          },
          {
            label: "Critical incidents",
            value: securityGate?.status ?? "Unavailable",
            icon: ShieldCheck,
          },
          {
            label: "Backup evidence",
            value: backupGate?.status ?? "Unavailable",
            icon: PackageCheck,
          },
          {
            label: "Release state",
            value: releaseReady ? "Ready" : "Blocked",
            icon: Rocket,
          },
        ].map((item) => (
          <div key={item.label} className="glass-card p-5">
            <item.icon className="h-5 w-5 text-electric-300" />
            <div className="mt-4 text-xl font-bold capitalize text-white">
              {item.value}
            </div>
            <div className="mt-1 text-xs text-white/35">{item.label}</div>
          </div>
        ))}
      </div>

      <section className="glass-card p-5">
        <h2 className="mb-4 text-sm font-semibold text-white">
          Mandatory Release Gates
        </h2>
        <div className="space-y-3">
          {!loading && items.length === 0 && (
            <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-4 text-sm text-white/45">
              No release gates are configured.
            </div>
          )}
          {items.map((gate) => {
            const passed = gate.status === "passed";
            const failed =
              gate.status === "blocked" || gate.status === "rejected";
            const approvalBlocked = gate.id === "approval" && !checksReady;
            return (
              <div
                key={gate.id}
                className="flex flex-col gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] p-4 sm:flex-row sm:items-center"
              >
                {passed ? (
                  <CheckCircle2 className="h-5 w-5 text-green-400" />
                ) : failed ? (
                  <XCircle className="h-5 w-5 text-red-300" />
                ) : (
                  <CircleDashed className="h-5 w-5 text-orange-300" />
                )}
                <div className="flex-1">
                  <div className="text-sm font-medium text-white">
                    {gate.name}
                  </div>
                  <div className="mt-1 text-xs text-white/35">
                    Responsible: {gate.owner}
                  </div>
                  {gate.lastResult && (
                    <div className="mt-1 text-xs text-white/45">
                      {gate.lastResult}
                    </div>
                  )}
                </div>
                <span
                  className={`rounded-full px-3 py-1 text-xs ${gateStatusClass[gate.status]}`}
                >
                  {gate.status}
                </span>
                {!passed && (
                  <button
                    onClick={() => validateGate(gate)}
                    disabled={busy || approvalBlocked}
                    className="rounded-lg border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs text-electric-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {gate.id === "approval" ? "Approve" : "Validate"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
