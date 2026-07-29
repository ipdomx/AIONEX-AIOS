"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Building2,
  CheckCircle2,
  CreditCard,
  PauseCircle,
  Search,
  ShieldCheck,
  Users,
  WalletCards,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

const supportedPlans = ["Starter", "Professional", "Enterprise"] as const;
type SupportedPlan = (typeof supportedPlans)[number];
type AccountPlan = SupportedPlan | "Free" | "Team";
type Status = "active" | "trial" | "past_due" | "suspended";

type Account = {
  id: string;
  organization: string;
  plan: AccountPlan;
  status: Status;
  seats: number;
  activeSeats: number;
  protected: boolean;
};

const statusClass: Record<Status, string> = {
  active: "border-green-500/20 bg-green-500/10 text-green-400",
  trial: "border-blue-500/20 bg-blue-500/10 text-blue-300",
  past_due: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  suspended: "border-red-500/20 bg-red-500/10 text-red-400",
};

export default function OwnerBillingPage() {
  const {
    items: accounts,
    loading,
    busy,
    message,
    execute,
  } = useOwnerResource<Account>("billing");
  const [query, setQuery] = useState("");

  const visible = useMemo(
    () =>
      accounts.filter((account) =>
        account.organization.toLowerCase().includes(query.toLowerCase()),
      ),
    [accounts, query],
  );
  const managedSeats = accounts.reduce(
    (total, account) => total + account.seats,
    0,
  );
  const activeSeats = accounts.reduce(
    (total, account) => total + account.activeSeats,
    0,
  );

  function changePlan(account: Account, nextPlan: SupportedPlan) {
    if (nextPlan === account.plan) return;
    if (
      !window.confirm(
        `Change ${account.organization} from ${account.plan} to ${nextPlan}?`,
      )
    ) {
      return;
    }
    void execute(account.id, "change-plan", { plan: nextPlan });
  }

  function toggleSubscription(account: Account) {
    const restoring = account.status === "suspended";
    if (
      !restoring &&
      !window.confirm(
        `Suspend ${account.organization}? Its users will lose platform access.`,
      )
    ) {
      return;
    }
    void execute(account.id, restoring ? "restore" : "suspend");
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
          <WalletCards className="h-3.5 w-3.5" /> Owner Billing Authority
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-white">
          Subscriptions, Plans & Billing
        </h1>
        <p className="mt-2 text-sm text-white/45">
          Control organization plan assignment, view seat use, and suspend or
          restore organization access.
        </p>
      </motion.div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="glass-card p-4">
          <Building2 className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {accounts.length}
          </div>
          <div className="text-xs text-white/35">Organizations</div>
        </div>
        <div className="glass-card p-4">
          <CreditCard className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {managedSeats}
          </div>
          <div className="text-xs text-white/35">Licensed seats</div>
        </div>
        <div className="glass-card p-4">
          <Users className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {activeSeats}
          </div>
          <div className="text-xs text-white/35">Active seats</div>
        </div>
        <div className="glass-card p-4">
          <ShieldCheck className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {accounts.filter((item) => item.status === "active").length}
          </div>
          <div className="text-xs text-white/35">Active</div>
        </div>
      </div>

      <div className="glass-card p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full max-w-xl">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search organizations..."
              className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none"
            />
          </div>
          <div className="flex items-center gap-2 text-xs text-electric-300">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {message}
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {loading ? (
          <div className="glass-card p-8 text-center text-sm text-white/40">
            Loading live billing accounts…
          </div>
        ) : visible.length === 0 ? (
          <div className="glass-card p-8 text-center text-sm text-white/40">
            No billing accounts match this search.
          </div>
        ) : (
          visible.map((account, index) => {
            return (
              <motion.div
                key={account.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className="glass-card p-5"
              >
                <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                  <div>
                    <h2 className="text-sm font-semibold text-white">
                      {account.organization}
                    </h2>
                    <p className="mt-1 text-xs text-white/40">
                      {account.plan} · {account.activeSeats} of {account.seats}{" "}
                      seats active
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full border px-2.5 py-1 text-xs ${statusClass[account.status]}`}
                    >
                      {account.status}
                    </span>
                    <select
                      disabled={busy}
                      value={
                        supportedPlans.includes(account.plan as SupportedPlan)
                          ? account.plan
                          : ""
                      }
                      onChange={(event) =>
                        changePlan(account, event.target.value as SupportedPlan)
                      }
                      className="glass-input rounded-lg px-3 py-2 text-xs text-white outline-none disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {!supportedPlans.includes(
                        account.plan as SupportedPlan,
                      ) && (
                        <option value="" disabled className="bg-space-800">
                          {account.plan} (legacy — choose a supported plan)
                        </option>
                      )}
                      {supportedPlans.map((plan) => (
                        <option
                          key={plan}
                          value={plan}
                          className="bg-space-800"
                        >
                          {plan}
                        </option>
                      ))}
                    </select>
                    <button
                      disabled={busy || account.protected}
                      onClick={() => toggleSubscription(account)}
                      className="rounded-lg border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <PauseCircle className="mr-1 inline h-3.5 w-3.5" />
                      {account.status === "suspended"
                        ? "Reactivate"
                        : account.protected
                          ? "Protected"
                          : "Suspend"}
                    </button>
                  </div>
                </div>
              </motion.div>
            );
          })
        )}
      </div>
    </div>
  );
}
