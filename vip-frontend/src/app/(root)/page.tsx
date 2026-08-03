"use client";

import Link from "next/link";
import { useEffect } from "react";

export default function RootPage() {
  useEffect(() => {
    window.location.replace("/ar/");
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#03050a] text-white">
      <Link href="/ar/" className="rounded-xl border border-white/10 px-5 py-3">
        AIONEX AIOS
      </Link>
    </main>
  );
}
