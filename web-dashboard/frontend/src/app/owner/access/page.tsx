"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Building2,
  KeyRound,
  LockKeyhole,
  ShieldCheck,
  UserCheck,
  Users,
} from "lucide-react";

import { GrowthSocialAccessConsole } from "@/components/owner/GrowthSocialAccessConsole";
import { useOwnerResource } from "@/hooks/use-owner-resource";

type OwnerRole = {
  id: string;
  name: string;
  organization: string;
  organizationId: string | null;
  scope: string;
  users: number;
  status: "active" | "suspended" | "protected";
};

type OrganizationGroup = {
  organization: string;
  roles: OwnerRole[];
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
  const normalizedQuery = query.trim().toLocaleLowerCase();

  const filtered = useMemo(
    () =>
      roles.filter((role) => {
        if (!normalizedQuery) return true;
        return [role.name, role.organization, role.scope].some((value) =>
          value.toLocaleLowerCase().includes(normalizedQuery),
        );
      }),
    [normalizedQuery, roles],
  );

  const groups = useMemo<OrganizationGroup[]>(() => {
    const grouped = new Map<string, OwnerRole[]>();
    for (const role of filtered) {
      const collection = grouped.get(role.organization) ?? [];
      collection.push(role);
      grouped.set(role.organization, collection);
    }
    return [...grouped.entries()]
      .map(([organization, organizationRoles]) => ({
        organization,
        roles: organizationRoles.sort((left, right) =>
          left.name.localeCompare(right.name),
        ),
      }))
      .sort((left, right) =>
        left.organization.localeCompare(right.organization),
      );
  }, [filtered]);

  const activeUsers = roles
    .filter((role) => role.status === "active" || role.status === "protected")
    .reduce((total, role) => total + role.users, 0);
  const organizationCount = new Set(roles.map((role) => role.organization))
    .size;

  const summary = [
    { label: "Role records", value: roles.length, icon: KeyRound },
    {
      label: "Organizations represented",
      value: organizationCount,
      icon: Building2,
    },
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
  ];

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

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {summary.map((item) => (
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
              account. Roles with the same name belong to different
              organizations and are grouped below.
            </p>
          </div>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search roles..."
            className="glass-input rounded-xl px-4 py-2 text-sm text-white outline-none"
          />
        </div>
        <div className="mb-4 text-xs text-electric-300">{message}</div>
        {loading ? (
          <div className="py-8 text-center text-sm text-white/40">
            Loading live access roles…
          </div>
        ) : groups.length === 0 ? (
          <div className="py-8 text-center text-sm text-white/40">
            No roles match the current search.
          </div>
        ) : (
          <div className="space-y-6">
            {groups.map((group) => (
              <section key={group.organization} className="space-y-3">
                <div className="flex items-center gap-2 border-b border-white/[0.06] pb-3">
                  <Building2 className="h-4 w-4 text-electric-300" />
                  <h3 className="text-sm font-semibold text-white">
                    {group.organization}
                  </h3>
                  <span className="rounded-full border border-white/[0.07] px-2 py-0.5 text-[10px] text-white/35">
                    {group.roles.length} role records
                  </span>
                </div>
                <div className="grid gap-3 xl:grid-cols-2">
                  {group.roles.map((role) => (
                    <div
                      key={role.id}
                      className="flex flex-col gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] p-4 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="min-w-0">
                        <div className="break-words text-sm font-semibold text-white">
                          {role.name}
                        </div>
                        <div className="mt-1 text-xs text-white/35">
                          Scope: {role.scope} · {role.users} users
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => void execute(role.id, "toggle")}
                        disabled={busy || role.status === "protected"}
                        className={`shrink-0 rounded-xl px-4 py-2 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-60 ${role.status === "active" ? "bg-green-500/10 text-green-400" : role.status === "suspended" ? "bg-orange-500/10 text-orange-300" : "cursor-not-allowed bg-white/[0.04] text-white/30"}`}
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
              </section>
            ))}
          </div>
        )}
      </div>
      <div className="border-t border-white/[0.06] pt-6">
        <GrowthSocialAccessConsole />
      </div>
    </div>
  );
}
