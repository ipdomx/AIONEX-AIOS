"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  KeyRound,
  LockKeyhole,
  ShieldCheck,
  UserCheck,
  Users,
} from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type OwnerRole = {
  id: string;
  name: string;
  scope: string;
  users: number;
  status: "active" | "suspended" | "protected";
};

export default function OwnerAccessPage() {
  const {
    items: roles,
    loading,
    busy,
    message,
    execute,
  } = useOwnerResource<OwnerRole>("access");
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () =>
      roles.filter((role) =>
        role.name.toLowerCase().includes(query.toLowerCase()),
      ),
    [roles, query],
  );
  const activeUsers = roles
    .filter((role) => role.status === "active" || role.status === "protected")
    .reduce((total, role) => total + role.users, 0);

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
          <ShieldCheck className="h-3.5 w-3.5" />
          Owner Access Authority
        </div>
        <h1 className="text-3xl font-bold text-white">
          Roles, Permissions & Session Control
        </h1>
        <p className="mt-2 text-sm text-white/45">
          Owner-only authority over role status, access scope, privileged
          sessions and identity governance.
        </p>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {[
          { label: "Privileged roles", value: roles.length, icon: KeyRound },
          { label: "Active users", value: activeUsers, icon: Users },
          {
            label: "Protected accounts",
            value: roles.filter((role) => role.status === "protected").length,
            icon: LockKeyhole,
          },
          {
            label: "Active roles",
            value: roles.filter((role) => role.status === "active").length,
            icon: UserCheck,
          },
        ].map((item) => (
          <div key={item.label} className="glass-card p-5">
            <item.icon className="h-5 w-5 text-electric-300" />
            <div className="mt-4 text-2xl font-bold text-white">
              {item.value}
            </div>
            <div className="mt-1 text-xs text-white/35">{item.label}</div>
          </div>
        ))}
      </div>

      <div className="glass-card p-5">
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">
              Role Authority Matrix
            </h2>
            <p className="mt-1 text-xs text-white/35">
              Suspend or restore roles without affecting the protected owner
              account.
            </p>
          </div>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search roles..."
            className="glass-input rounded-xl px-4 py-2 text-sm text-white outline-none"
          />
        </div>
        <div className="mb-3 text-xs text-electric-300">{message}</div>
        {loading ? (
          <div className="py-8 text-center text-sm text-white/40">
            Loading live access roles…
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((role) => (
              <div
                key={role.id}
                className="flex flex-col gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] p-4 md:flex-row md:items-center md:justify-between"
              >
                <div>
                  <div className="text-sm font-semibold text-white">
                    {role.name}
                  </div>
                  <div className="mt-1 text-xs text-white/35">
                    Scope: {role.scope} · {role.users} users
                  </div>
                </div>
                <button
                  onClick={() => void execute(role.id, "toggle")}
                  disabled={busy || role.status === "protected"}
                  className={`rounded-xl px-4 py-2 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-60 ${role.status === "active" ? "bg-green-500/10 text-green-400" : role.status === "suspended" ? "bg-orange-500/10 text-orange-300" : "cursor-not-allowed bg-white/[0.04] text-white/30"}`}
                >
                  {role.status === "protected"
                    ? "Protected"
                    : busy
                      ? "Updating…"
                      : role.status === "active"
                        ? "Active"
                        : "Suspended"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
