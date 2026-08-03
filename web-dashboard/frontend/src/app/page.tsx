"use client";

import { useEffect } from "react";
import { LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/providers/AuthProvider";

export default function ControlPlaneEntryPage() {
  const { user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!user) return;
    router.replace("/owner");
  }, [router, user]);

  return (
    <section
      aria-busy="true"
      aria-label="Opening authorized workspace"
      className="flex min-h-[calc(100vh-7rem)] items-center justify-center"
    >
      <div className="flex items-center gap-3 text-sm text-white/45">
        <LoaderCircle className="h-5 w-5 animate-spin text-electric-300" />
        Opening authorized workspace…
      </div>
    </section>
  );
}
