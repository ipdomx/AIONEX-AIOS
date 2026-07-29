"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Building2,
  CheckCircle2,
  CircleDollarSign,
  LockKeyhole,
  RefreshCw,
  Search,
  ShieldAlert,
  Users,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type OwnerOrganization = {
  id: string;
  name: string;
  plan: string;
  users: number;
  projects: number;
  services: number | null;
  status: string;
  risk: string;
  protected: boolean;
  updatedAt: string;
};

export default function OwnerOrganizationsPage() {
  const { items, loading, busy, message, reload, execute } =
    useOwnerResource<OwnerOrganization>("organizations");
  const [query, setQuery] = useState("");

  const organizations = useMemo(
    () =>
      items.filter((organization) =>
        `${organization.name} ${organization.plan} ${organization.status}`
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
    [items, query],
  );

  const managedUsers = items.reduce(
    (total, organization) => total + organization.users,
    0,
  );
  const restricted = items.filter((organization) =>
    ["restricted", "suspended", "inactive"].includes(organization.status),
  ).length;

  function toggleRestriction(organization: OwnerOrganization) {
    const restoring = ["restricted", "suspended", "inactive"].includes(
      organization.status,
    );
    if (
      !restoring &&
      !window.confirm(
        `Restrict ${organization.name}? Its users will lose platform access.`,
      )
    ) {
      return;
    }
    void execute(organization.id, restoring ? "restore" : "restrict");
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <Building2 className="h-3.5 w-3.5" /> Owner Organization Command
          </div>
          <h1 className="text-3xl font-bold text-white">
            Organizations &amp; Tenants
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Global control of plans, users, services, policies, risk and
            organization boundaries.
          </p>
        </div>
        <button
          onClick={() => void reload()}
          disabled={loading || busy}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh organizations
        </button>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: "Organizations", value: items.length, icon: Building2 },
          { label: "Managed users", value: managedUsers, icon: Users },
          {
            label: "Restricted tenants",
            value: restricted,
            icon: LockKeyhole,
          },
          {
            label: "Active plans",
            value: new Set(items.map((item) => item.plan)).size,
            icon: CircleDollarSign,
          },
        ].map((item) => (
          <div key={item.label} className="glass-card p-5">
            <item.icon className="h-5 w-5 text-electric-300" />
            <div className="mt-4 text-2xl font-bold text-white">
              {item.value.toLocaleString()}
            </div>
            <div className="mt-1 text-xs text-white/35">{item.label}</div>
          </div>
        ))}
      </div>

      <div className="glass-card p-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search organizations, plans or status..."
            className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none"
          />
        </div>
        <div className="mt-3 text-xs text-electric-300">
          {loading ? "Loading organizations..." : message}
        </div>
      </div>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {!loading && organizations.length === 0 && (
          <div className="glass-card p-6 text-sm text-white/45 xl:col-span-3">
            No organizations match the current search.
          </div>
        )}
        {organizations.map((organization) => {
          const isRestricted = ["restricted", "suspended", "inactive"].includes(
            organization.status,
          );
          return (
            <div key={organization.id} className="glass-card p-5">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-sm font-semibold text-white">
                    {organization.name}
                  </h2>
                  <p className="mt-1 text-xs text-white/40">
                    {organization.plan} plan
                  </p>
                </div>
                {organization.risk === "high" ? (
                  <ShieldAlert className="h-5 w-5 text-red-400" />
                ) : (
                  <CheckCircle2 className="h-5 w-5 text-green-400" />
                )}
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3 text-center">
                <div className="rounded-lg bg-white/[0.02] p-3">
                  <div className="text-sm font-bold text-white">
                    {organization.users}
                  </div>
                  <div className="text-[10px] text-white/30">Users</div>
                </div>
                <div className="rounded-lg bg-white/[0.02] p-3">
                  <div className="text-sm font-bold text-white">
                    {organization.projects}
                  </div>
                  <div className="text-[10px] text-white/30">Projects</div>
                </div>
                <div className="rounded-lg bg-white/[0.02] p-3">
                  <div className="text-sm font-bold text-white">
                    {organization.services ?? "—"}
                  </div>
                  <div className="text-[10px] text-white/30">Services</div>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-white/[0.05] pt-4">
                <span className="text-xs text-white/40">
                  {organization.status}
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => toggleRestriction(organization)}
                    disabled={busy || organization.protected}
                    className={`rounded-lg border px-3 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-50 ${
                      isRestricted
                        ? "border-green-500/20 bg-green-500/10 text-green-300"
                        : "border-red-500/20 bg-red-500/10 text-red-300"
                    }`}
                  >
                    {organization.protected
                      ? "Protected"
                      : isRestricted
                        ? "Restore"
                        : "Restrict"}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}
