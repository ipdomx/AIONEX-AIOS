"use client";

import Link from "next/link";
import { LoaderCircle, ShieldAlert } from "lucide-react";

import { useAuth } from "@/components/providers/AuthProvider";

export default function SuperOwnerGuard({
  children,
}: {
  children: React.ReactNode;
}) {
  const { loading, user } = useAuth();

  if (loading) {
    return (
      <section
        aria-busy="true"
        aria-label="Restoring owner session"
        className="flex min-h-[calc(100vh-7rem)] items-center justify-center"
      >
        <div className="flex items-center gap-3 text-sm text-white/45">
          <LoaderCircle className="h-5 w-5 animate-spin text-electric-300" />
          Restoring owner session…
        </div>
      </section>
    );
  }

  if (user?.role === "Super Owner") {
    return <>{children}</>;
  }

  return (
    <section className="flex min-h-[calc(100vh-7rem)] items-center justify-center">
      <section className="glass-card w-full max-w-xl p-8 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-red-500/20 bg-red-500/10">
          <ShieldAlert className="h-7 w-7 text-red-300" />
        </div>
        <h1 className="mt-5 text-2xl font-semibold text-white">
          Super Owner access required
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-white/45">
          The global Owner Dashboard is restricted to the platform Super Owner.
          Organization owners remain limited to their organization-scoped
          controls.
        </p>
        <Link href="/" className="btn-primary mt-6 inline-flex">
          Return to dashboard
        </Link>
      </section>
    </section>
  );
}
