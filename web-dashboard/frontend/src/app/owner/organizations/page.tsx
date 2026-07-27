"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Building2, CheckCircle2, CircleDollarSign, LockKeyhole, ShieldAlert, Users } from "lucide-react";

const organizations = [
  { name: "AIONEX Corp", plan: "Enterprise", users: 2847, projects: 12, services: 18, status: "active", risk: "low" },
  { name: "AIONEX Labs", plan: "Research", users: 184, projects: 4, services: 11, status: "active", risk: "medium" },
  { name: "Partner Sandbox", plan: "Controlled", users: 37, projects: 2, services: 5, status: "restricted", risk: "high" },
];

export default function OwnerOrganizationsPage() {
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300"><Building2 className="h-3.5 w-3.5" /> Owner Organization Command</div>
          <h1 className="text-3xl font-bold text-white">Organizations & Tenants</h1>
          <p className="mt-2 text-sm text-white/45">Global control of plans, users, services, policies, risk and organization boundaries.</p>
        </div>
        <Link href="/users/organizations" className="btn-primary">Open organization management</Link>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: "Organizations", value: "18", icon: Building2 },
          { label: "Managed users", value: "3,068", icon: Users },
          { label: "Restricted tenants", value: "2", icon: LockKeyhole },
          { label: "Billing exceptions", value: "1", icon: CircleDollarSign },
        ].map((item) => <div key={item.label} className="glass-card p-5"><item.icon className="h-5 w-5 text-electric-300" /><div className="mt-4 text-2xl font-bold text-white">{item.value}</div><div className="mt-1 text-xs text-white/35">{item.label}</div></div>)}
      </div>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {organizations.map((organization) => (
          <div key={organization.name} className="glass-card p-5">
            <div className="flex items-start justify-between">
              <div><h2 className="text-sm font-semibold text-white">{organization.name}</h2><p className="mt-1 text-xs text-white/40">{organization.plan} plan</p></div>
              {organization.risk === "high" ? <ShieldAlert className="h-5 w-5 text-red-400" /> : <CheckCircle2 className="h-5 w-5 text-green-400" />}
            </div>
            <div className="mt-5 grid grid-cols-3 gap-3 text-center">
              <div className="rounded-lg bg-white/[0.02] p-3"><div className="text-sm font-bold text-white">{organization.users}</div><div className="text-[10px] text-white/30">Users</div></div>
              <div className="rounded-lg bg-white/[0.02] p-3"><div className="text-sm font-bold text-white">{organization.projects}</div><div className="text-[10px] text-white/30">Projects</div></div>
              <div className="rounded-lg bg-white/[0.02] p-3"><div className="text-sm font-bold text-white">{organization.services}</div><div className="text-[10px] text-white/30">Services</div></div>
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-white/[0.05] pt-4"><span className="text-xs text-white/40">{organization.status}</span><div className="flex gap-2"><button className="rounded-lg border border-white/[0.08] px-3 py-1.5 text-xs text-white/60 hover:bg-white/[0.06]">Review</button><button className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-1.5 text-xs text-red-300">Restrict</button></div></div>
          </div>
        ))}
      </section>
    </div>
  );
}
