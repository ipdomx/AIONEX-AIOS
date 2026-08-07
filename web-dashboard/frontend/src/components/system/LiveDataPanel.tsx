"use client";

import { ReactNode } from "react";

export function LiveDataPanel({ title, subtitle, loading, error, empty, children }:{title:string;subtitle:string;loading:boolean;error:string|null;empty:boolean;children:ReactNode}) {
  return <div className="space-y-6">
    <div><h1 className="text-2xl font-bold text-white tracking-tight">{title}</h1><p className="mt-1 text-sm text-white/40">{subtitle}</p></div>
    {loading && <div className="glass-card p-6 text-sm text-white/50">Loading live data…</div>}
    {error && <div className="glass-card p-6 text-sm text-red-300">{error}</div>}
    {!loading && !error && empty && <div className="glass-card p-6 text-sm text-white/50">No live records are currently available.</div>}
    {!loading && !error && !empty && children}
  </div>;
}

export function JsonCard({ title, value, actions }:{title:string;value:unknown;actions?:ReactNode}) {
  return <section className="glass-card p-5"><div className="mb-3 flex items-start justify-between gap-4"><h2 className="font-semibold text-white">{title}</h2>{actions}</div><pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs text-white/55">{JSON.stringify(value,null,2)}</pre></section>;
}
