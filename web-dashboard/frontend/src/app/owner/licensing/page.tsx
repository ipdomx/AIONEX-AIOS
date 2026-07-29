"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import {
  BadgeCheck,
  CircleDollarSign,
  KeyRound,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Users,
} from "lucide-react";
import {
  fetchOwnerLicenses,
  updateOwnerLicense,
  type LicenseRecord,
} from "@/lib/owner-licensing";

const statusClass: Record<LicenseRecord["status"], string> = {
  active: "border-green-500/20 bg-green-500/10 text-green-300",
  expiring: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  suspended: "border-red-500/20 bg-red-500/10 text-red-300",
  pending: "border-blue-500/20 bg-blue-500/10 text-blue-300",
};

type SummaryCard = { label: string; value: string | number; icon: LucideIcon };

export default function OwnerLicensingPage() {
  const [items, setItems] = useState<LicenseRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading licenses...");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchOwnerLicenses(signal);
      setItems(data);
      setMessage("License registry synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setItems([]);
        setMessage("Licensing backend contract is not available.");
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
      active: items.filter((item) => item.status === "active").length,
      seats: items.reduce((total, item) => total + item.seats, 0),
      activeSeats: items.reduce((total, item) => total + item.activeSeats, 0),
      monthlyValue: items.reduce((total, item) => total + item.monthlyValue, 0),
    }),
    [items],
  );

  const cards: SummaryCard[] = [
    { label: "Active licenses", value: summary.active, icon: BadgeCheck },
    { label: "Total seats", value: summary.seats, icon: Users },
    { label: "Active seats", value: summary.activeSeats, icon: Users },
    {
      label: "Monthly value",
      value: `€${summary.monthlyValue.toLocaleString()}`,
      icon: CircleDollarSign,
    },
  ];

  async function act(id: string, action: "renew" | "suspend" | "restore") {
    setMessage(`Submitting ${action} action...`);
    try {
      const updated = await updateOwnerLicense(id, action);
      setItems((current) =>
        current.map((item) => (item.id === id ? updated : item)),
      );
      setMessage(`License action completed: ${action}.`);
    } catch {
      setMessage("License action failed and was not persisted.");
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
            <KeyRound className="h-3.5 w-3.5" /> Owner Licensing
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Enterprise Licensing & Entitlements
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Owner control for plans, seats, renewals, suspensions, restoration
            and commercial visibility.
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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {cards.map(({ label, value, icon: Icon }) => (
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
                  {item.organization}
                </h2>
                <p className="mt-1 text-xs text-white/40">
                  {item.plan} plan · expires {item.expiresAt}
                </p>
              </div>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[item.status]}`}
              >
                {item.status}
              </span>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-3">
              <div className="rounded-lg bg-white/[0.02] p-3">
                <div className="text-[10px] uppercase tracking-wider text-white/30">
                  Seats
                </div>
                <div className="mt-1 text-sm font-semibold text-white">
                  {item.seats}
                </div>
              </div>
              <div className="rounded-lg bg-white/[0.02] p-3">
                <div className="text-[10px] uppercase tracking-wider text-white/30">
                  Active
                </div>
                <div className="mt-1 text-sm font-semibold text-white">
                  {item.activeSeats}
                </div>
              </div>
              <div className="rounded-lg bg-white/[0.02] p-3">
                <div className="text-[10px] uppercase tracking-wider text-white/30">
                  Monthly
                </div>
                <div className="mt-1 text-sm font-semibold text-white">
                  €{item.monthlyValue.toLocaleString()}
                </div>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                onClick={() => void act(item.id, "renew")}
                className="rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300"
              >
                <RotateCcw className="mr-1 inline h-3.5 w-3.5" />
                Renew
              </button>
              {item.status === "suspended" ? (
                <button
                  onClick={() => void act(item.id, "restore")}
                  className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-xs text-blue-300"
                >
                  <BadgeCheck className="mr-1 inline h-3.5 w-3.5" />
                  Restore
                </button>
              ) : (
                <button
                  onClick={() => void act(item.id, "suspend")}
                  className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300"
                >
                  <ShieldAlert className="mr-1 inline h-3.5 w-3.5" />
                  Suspend
                </button>
              )}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
