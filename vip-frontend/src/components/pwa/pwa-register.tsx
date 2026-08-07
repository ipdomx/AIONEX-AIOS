"use client";

import { useEffect } from "react";

export function PwaRegister() {
  useEffect(() => {
    if (
      !("serviceWorker" in navigator) ||
      process.env.NODE_ENV !== "production"
    ) {
      return;
    }

    let reloading = false;
    let registration: ServiceWorkerRegistration | null = null;
    const applyWaitingWorker = () => {
      registration?.waiting?.postMessage({ type: "SKIP_WAITING" });
    };
    const onControllerChange = () => {
      if (reloading) return;
      reloading = true;
      window.location.reload();
    };
    const onOnline = () => {
      void registration?.update();
    };

    navigator.serviceWorker.addEventListener(
      "controllerchange",
      onControllerChange,
    );
    window.addEventListener("online", onOnline);

    const register = async () => {
      try {
        registration = await navigator.serviceWorker.register("/sw.js", {
          scope: "/",
          updateViaCache: "none",
        });
        if (registration.waiting && navigator.serviceWorker.controller) {
          applyWaitingWorker();
        }
        registration.addEventListener("updatefound", () => {
          const installing = registration?.installing;
          installing?.addEventListener("statechange", () => {
            if (
              installing.state === "installed" &&
              navigator.serviceWorker.controller
            ) {
              applyWaitingWorker();
            }
          });
        });
      } catch {
        registration = null;
      }
    };

    if (document.readyState === "complete") void register();
    else window.addEventListener("load", register, { once: true });
    const interval = window.setInterval(
      () => void registration?.update(),
      6 * 60 * 60 * 1000,
    );

    return () => {
      window.removeEventListener("load", register);
      window.removeEventListener("online", onOnline);
      navigator.serviceWorker.removeEventListener(
        "controllerchange",
        onControllerChange,
      );
      window.clearInterval(interval);
    };
  }, []);
  return null;
}
