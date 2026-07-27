"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { KeyRound, LockKeyhole, ShieldCheck, UserCheck, Users } from "lucide-react";

const initialAccess = [
  { id: "role-owner", name: "Owner", scope: "Global", users: 1, status: "protected" },
  { id: "role-chief", name: "Chief Engineer", scope: "Engineering", users: 3, status: "active" },
  { id: "role-manager", name: "Manager", scope: "Department", users: 12, status: "active" },
  { id: "role-engineer", name: "Engineer", scope: "Project", users: 48, status: "active" },
  { id: "role-employee", name: "Employee", scope: "Task", users: 126, status: "active" },
];

export default function OwnerAccessPage() {
  const [roles, setRoles] = useState(initialAccess);
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => roles.filter((role) => role.name.toLowerCase().includes(query.toLowerCase())), [roles, query]);

  function toggleRole(id: string) {
    setRoles((current) => current.map((role) => role.id === id && role.status !== "protected" ? { ...role, status: role.status === "active" ? "suspended" : "active" } : role));
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300"><ShieldCheck className="h-3.5 w-3.5" />Owner Access Authority</div>
        <h1 className="text-3xl font-bold text-white">Roles, Permissions & Session Control</h1>
        <p className="mt-2 text-sm text-white/45">Owner-only authority over role status, access scope, privileged sessions and identity governance.</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {[{ label: "Privileged roles", value: "5", icon: KeyRound }, { label: "Active users", value: "190", icon: Users }, { label: "Protected accounts", value: "1", icon: LockKeyhole }, { label: "Verified sessions", value: "14", icon: UserCheck }].map((item) => <div key={item.label} className="glass-card p-5"><item.icon className="h-5 w-5 text-electric-300" /><div className="mt-4 text-2xl font-bold text-white">{item.value}</div><div className="mt-1 text-xs text-white/35">{item.label}</div></div>)}
      </div>

      <div className="glass-card p-5">
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between"><div><h2 className="text-sm font-semibold text-white">Role Authority Matrix</h2><p className="mt-1 text-xs text-white/35">Suspend or restore roles without affecting the protected owner account.</p></div><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search roles..." className="glass-input rounded-xl px-4 py-2 text-sm text-white outline-none" /></div>
        <div className="space-y-3">{filtered.map((role) => <div key={role.id} className="flex flex-col gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] p-4 md:flex-row md:items-center md:justify-between"><div><div className="text-sm font-semibold text-white">{role.name}</div><div className="mt-1 text-xs text-white/35">Scope: {role.scope} · {role.users} users</div></div><button onClick={() => toggleRole(role.id)} disabled={role.status === "protected"} className={`rounded-xl px-4 py-2 text-xs font-medium ${role.status === "active" ? "bg-green-500/10 text-green-400" : role.status === "suspended" ? "bg-orange-500/10 text-orange-300" : "cursor-not-allowed bg-white/[0.04] text-white/30"}`}>{role.status === "protected" ? "Protected" : role.status === "active" ? "Active" : "Suspended"}</button></div>)}</div>
      </div>
    </div>
  );
}
