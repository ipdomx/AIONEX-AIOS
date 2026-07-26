"use client";

import { PropsWithChildren, useEffect, useState } from "react";

import { IntegrationHealth, runtimeServices } from "@/lib/runtime-services";

type RuntimeState = {
  loading: boolean;
  health: IntegrationHealth | null;
  error: string | null;
};

export default function RuntimeProvider({ children }: PropsWithChildren) {
  const [state, setState] = useState<RuntimeState>({ loading: true, health: null, error: null });

  useEffect(() => {
    let cancelled = false;

    async function verifyRuntime() {
      try {
        const health = await runtimeServices.integrationHealth();
        if (!cancelled) setState({ loading: false, health, error: null });
      } catch (error) {
        if (!cancelled) {
          setState({ loading: false, health: null, error: error instanceof Error ? error.message : "Runtime unavailable" });
        }
      }
    }

    void verifyRuntime();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      {state.error && (
        <div className="fixed right-4 top-4 z-[100] max-w-sm rounded-xl border border-amber-500/20 bg-space-900/95 px-4 py-3 text-xs text-amber-200 shadow-xl backdrop-blur-xl">
          AIOS runtime is unavailable: {state.error}
        </div>
      )}
      {children}
    </>
  );
}
