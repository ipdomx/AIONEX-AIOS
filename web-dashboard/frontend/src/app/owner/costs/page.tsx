"use client";

import { useMemo, type FormEvent } from "react";
import { motion } from "framer-motion";
import { Bot, Cloud, Coins, Database, Server, ShieldCheck } from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type BudgetItem = {
  id: string;
  service: string;
  category: string;
  monthlyLimit: number;
  used: number | null;
  enabled: boolean;
};

const iconFor = (category: string) =>
  category === "AI Provider"
    ? Bot
    : category === "Infrastructure"
      ? Cloud
      : Database;

export default function OwnerCostsPage() {
  const {
    items: budgets,
    loading,
    busy,
    message,
    execute,
  } = useOwnerResource<BudgetItem>("costs");
  const totalLimit = useMemo(
    () => budgets.reduce((sum, item) => sum + item.monthlyLimit, 0),
    [budgets],
  );
  function updateLimit(event: FormEvent<HTMLFormElement>, item: BudgetItem) {
    event.preventDefault();
    const value = Number(new FormData(event.currentTarget).get("monthlyLimit"));
    if (!Number.isFinite(value)) return;
    void execute(item.id, "set-limit", {
      monthlyLimit: Math.max(value, 0),
    });
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
          <Coins className="h-3.5 w-3.5" /> Owner Cost Governance
        </div>
        <h1 className="mt-3 text-3xl font-bold text-white">
          Cost, Usage & Service Limits
        </h1>
        <p className="mt-2 text-sm text-white/45">
          Record Owner-approved budget targets. Usage remains explicitly
          unavailable until a billing telemetry source is connected.
        </p>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {[
          {
            label: "Monthly Budget",
            value: `$${totalLimit.toLocaleString()}`,
            icon: ShieldCheck,
          },
          {
            label: "Limited Services",
            value: budgets
              .filter((item) => item.monthlyLimit > 0)
              .length.toString(),
            icon: ShieldCheck,
          },
          {
            label: "No Limit",
            value: budgets
              .filter((item) => item.monthlyLimit === 0)
              .length.toString(),
            icon: Coins,
          },
          {
            label: "Telemetry Linked",
            value: budgets
              .filter((item) => item.used !== null)
              .length.toString(),
            icon: Server,
          },
        ].map((item) => {
          const Icon = item.icon;
          return (
            <div key={item.label} className="glass-card p-5">
              <div className="flex items-center justify-between">
                <Icon className="h-5 w-5 text-electric-300" />
                <span className="text-2xl font-bold text-white">
                  {item.value}
                </span>
              </div>
              <p className="mt-3 text-xs uppercase tracking-wider text-white/35">
                {item.label}
              </p>
            </div>
          );
        })}
      </div>

      <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-xs text-electric-300">
        {message}
      </div>

      <div className="space-y-4">
        {loading ? (
          <div className="glass-card p-8 text-center text-sm text-white/40">
            Loading live cost controls…
          </div>
        ) : budgets.length === 0 ? (
          <div className="glass-card p-8 text-center text-sm text-white/40">
            No service budgets are configured.
          </div>
        ) : (
          budgets.map((item, index) => {
            const Icon = iconFor(item.category);
            return (
              <motion.div
                key={item.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.04 }}
                className="glass-card p-5"
              >
                <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                      <Icon className="h-5 w-5 text-electric-300" />
                    </div>
                    <div>
                      <h2 className="text-sm font-semibold text-white">
                        {item.service}
                      </h2>
                      <p className="mt-1 text-xs text-white/35">
                        {item.category}
                      </p>
                    </div>
                  </div>
                  <div className="w-full max-w-xl text-xs text-white/50">
                    <div>
                      Approved monthly limit:{" "}
                      <span className="font-medium text-white/75">
                        {item.monthlyLimit > 0
                          ? `$${item.monthlyLimit.toLocaleString()}`
                          : "No limit configured"}
                      </span>
                    </div>
                    <div className="mt-1 text-white/30">
                      Usage telemetry:{" "}
                      {item.used === null
                        ? "not connected"
                        : `$${item.used.toLocaleString()}`}
                    </div>
                  </div>
                  <form
                    onSubmit={(event) => updateLimit(event, item)}
                    className="flex flex-wrap items-center gap-2"
                  >
                    <input
                      key={item.monthlyLimit}
                      disabled={busy}
                      name="monthlyLimit"
                      type="number"
                      min={0}
                      defaultValue={item.monthlyLimit}
                      className="glass-input w-32 rounded-xl px-3 py-2 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50"
                    />
                    <button
                      disabled={busy}
                      type="submit"
                      className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-2 text-xs font-medium text-electric-300 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Save limit
                    </button>
                  </form>
                </div>
              </motion.div>
            );
          })
        )}
      </div>
    </div>
  );
}
