"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

export function ThemeToggle({ label }: { label: string }) {
  const [light, setLight] = useState(false);

  useEffect(() => {
    const stored = window.localStorage.getItem("aionex.theme");
    const nextLight = stored === "light";
    document.documentElement.classList.toggle("light", nextLight);
    setLight(nextLight);
  }, []);

  function toggle() {
    const next = !light;
    setLight(next);
    document.documentElement.classList.toggle("light", next);
    window.localStorage.setItem("aionex.theme", next ? "light" : "dark");
  }

  return (
    <button className="icon-button" type="button" onClick={toggle} aria-label={label}>
      {light ? <Moon aria-hidden="true" /> : <Sun aria-hidden="true" />}
    </button>
  );
}
