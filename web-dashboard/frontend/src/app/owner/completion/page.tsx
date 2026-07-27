"use client";

import Link from "next/link";
import { CheckCircle2, ClipboardCheck, ExternalLink, ShieldCheck } from "lucide-react";

const sections = [
  ["Executive overview", "/owner/executive"],
  ["System health", "/owner/system-health"],
  ["Projects command", "/owner/projects"],
  ["Organizations command", "/owner/organizations"],
  ["Approvals", "/owner/approvals"],
  ["Notifications", "/owner/notifications"],
  ["Service control", "/owner/services"],
  ["Incident command", "/owner/incidents"],
  ["Audit and accountability", "/owner/audit"],
  ["Cost governance", "/owner/costs"],
  ["Staff oversight", "/owner/staff"],
  ["Councils and ministries", "/owner/governance"],
  ["Communications", "/owner/communications"],
  ["Recovery center", "/owner/recovery"],
  ["Access authority", "/owner/access"],
  ["Release authority", "/owner/release"],
];

export default function OwnerCompletionPage() {
  return (
    <div className="space-y-6">
      <header className="glass-card p-6">
        <div className="flex items-center gap-3"><ShieldCheck className="h-7 w-7 text-green-400" /><div><h1 className="text-2xl font-bold text-white">Owner Dashboard Completion</h1><p className="mt-1 text-sm text-white/45">Final consolidated inventory of owner command and governance capabilities.</p></div></div>
      </header>
      <section className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {sections.map(([label, href]) => (
          <Link key={href} href={href} className="glass-card flex items-center gap-3 p-4 transition hover:bg-white/[0.05]">
            <CheckCircle2 className="h-5 w-5 text-green-400" />
            <span className="flex-1 text-sm font-medium text-white/75">{label}</span>
            <ExternalLink className="h-4 w-4 text-white/25" />
          </Link>
        ))}
      </section>
      <section className="glass-card p-5">
        <div className="flex items-start gap-3"><ClipboardCheck className="mt-0.5 h-5 w-5 text-electric-300" /><div><h2 className="text-sm font-semibold text-white">Final deployment gate</h2><p className="mt-2 text-xs leading-relaxed text-white/45">Deploy only after CodeQL and Final Validation succeed, then perform one server pull and one container rebuild for the complete owner dashboard release.</p></div></div>
      </section>
    </div>
  );
}
