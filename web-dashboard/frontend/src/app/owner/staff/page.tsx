"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Briefcase, Building2, Search, UserCog, Users } from "lucide-react";

import { useOwnerResource } from "@/hooks/use-owner-resource";

type StaffMember = {
  id: string;
  name: string;
  department: string;
  organization: string;
  status: string;
};

export default function OwnerStaffPage() {
  const { items, loading, message } = useOwnerResource<StaffMember>("staff");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const visible = useMemo(
    () =>
      items.filter(
        (item) =>
          (status === "all" || item.status === status) &&
          `${item.name} ${item.department} ${item.organization}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [items, query, status],
  );
  const statusOptions = useMemo(
    () => ["all", ...Array.from(new Set(items.map((item) => item.status)))],
    [items],
  );

  const activeStaff = items.filter((item) => item.status === "active").length;
  const departments = new Set(items.map((item) => item.department)).size;
  const organizations = new Set(items.map((item) => item.organization)).size;
  const suspendedStaff = items.filter(
    (item) => item.status !== "active",
  ).length;

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
      >
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-purple-500/20 bg-purple-500/10 px-3 py-1 text-xs font-medium text-purple-300">
            <UserCog className="h-3.5 w-3.5" />
            Owner Staff Oversight
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Staff Identity &amp; Status
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-white/45">
            Owner-only visibility into internal roles, departments,
            organizations and current operating status.
          </p>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: "Active Staff", value: activeStaff, icon: Users },
          { label: "Departments", value: departments, icon: Briefcase },
          {
            label: "Organizations",
            value: organizations,
            icon: Building2,
          },
          {
            label: "Non-active Accounts",
            value: suspendedStaff,
            icon: UserCog,
          },
        ].map((item) => (
          <div key={item.label} className="glass-card p-5">
            <item.icon className="h-5 w-5 text-purple-300" />
            <div className="mt-4 text-2xl font-bold text-white">
              {item.value}
            </div>
            <div className="mt-1 text-xs uppercase tracking-wider text-white/35">
              {item.label}
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search staff, department or organization..."
              className="glass-input w-full rounded-xl py-2.5 pl-10 pr-4 text-sm text-white outline-none"
            />
          </div>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="glass-input rounded-xl px-4 py-2.5 text-sm text-white outline-none"
          >
            {statusOptions.map((option) => (
              <option key={option} value={option} className="bg-space-800">
                {option === "all" ? "All Status" : option}
              </option>
            ))}
          </select>
        </div>
        <div className="text-xs text-electric-300">
          {loading ? "Loading staff records..." : message}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {!loading && visible.length === 0 && (
          <div className="glass-card p-6 text-sm text-white/45 lg:col-span-2">
            No staff records match the current filters.
          </div>
        )}
        {visible.map((member, index) => (
          <motion.section
            key={member.id}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.04 }}
            className="glass-card p-5"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-3">
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.04] p-2.5">
                    <UserCog className="h-5 w-5 text-purple-300" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-white">
                      {member.name}
                    </h2>
                    <p className="text-xs text-white/40">
                      {member.department} · {member.organization}
                    </p>
                  </div>
                </div>
              </div>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs ${
                  member.status === "active"
                    ? "border-green-500/20 bg-green-500/10 text-green-400"
                    : "border-orange-500/20 bg-orange-500/10 text-orange-400"
                }`}
              >
                {member.status}
              </span>
            </div>
            <div className="mt-4 border-t border-white/[0.05] pt-4 text-xs text-white/45">
              Account status is read directly from the identity database.
            </div>
          </motion.section>
        ))}
      </div>
    </div>
  );
}
