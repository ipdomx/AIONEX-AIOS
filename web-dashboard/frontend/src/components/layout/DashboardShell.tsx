"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Palette } from "lucide-react";
import Link from "next/link";

import LanguageVoiceControls from "@/components/accessibility/LanguageVoiceControls";
import { useLanguageVoice } from "@/components/providers/LanguageVoiceProvider";
import CommandPalette from "@/components/layout/CommandPalette";
import Sidebar from "@/components/layout/Sidebar";
import TopBar from "@/components/layout/TopBar";
import GlobalSearch from "@/components/search/GlobalSearch";

export default function DashboardShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const { decision } = useLanguageVoice();
  const isRtl = decision.direction === "rtl";
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [globalSearchOpen, setGlobalSearchOpen] = useState(false);

  const toggleSidebar = useCallback(
    () => setSidebarCollapsed((current) => !current),
    [],
  );

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1023px)");
    const updateMobile = () => {
      setMobile(media.matches);
      if (!media.matches) setMobileSidebarOpen(false);
    };
    updateMobile();
    media.addEventListener("change", updateMobile);
    return () => media.removeEventListener("change", updateMobile);
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        (event.metaKey || event.ctrlKey) &&
        event.shiftKey &&
        event.key.toLowerCase() === "k"
      ) {
        event.preventDefault();
        setGlobalSearchOpen((current) => !current);
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandPaletteOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="min-h-screen overflow-x-hidden bg-space-950">
      {mobile && mobileSidebarOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-[45] bg-black/70 backdrop-blur-sm"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}
      <Sidebar
        collapsed={mobile ? false : sidebarCollapsed}
        mobile={mobile}
        open={!mobile || mobileSidebarOpen}
        onToggle={mobile ? () => setMobileSidebarOpen(false) : toggleSidebar}
        onNavigate={() => {
          if (mobile) setMobileSidebarOpen(false);
        }}
      />
      <TopBar
        sidebarCollapsed={sidebarCollapsed}
        mobile={mobile}
        onMenuOpen={() => setMobileSidebarOpen(true)}
        onSearchOpen={() => setGlobalSearchOpen(true)}
        onCommandOpen={() => setCommandPaletteOpen(true)}
      />
      <motion.main
        initial={false}
        animate={{
          marginLeft: isRtl || mobile ? 0 : sidebarCollapsed ? 72 : 280,
          marginRight: !isRtl || mobile ? 0 : sidebarCollapsed ? 72 : 280,
        }}
        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        className="min-h-screen min-w-0 px-3 pb-24 pt-20 sm:px-5 lg:px-6"
      >
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3 }}
          className="mx-auto w-full min-w-0 max-w-[1600px]"
        >
          {children}
        </motion.div>
      </motion.main>
      <Link
        href="/studio"
        className="fixed bottom-5 start-4 z-40 flex items-center gap-2 rounded-full border border-electric-400/30 bg-space-900/95 px-4 py-2.5 text-sm font-semibold text-white shadow-xl backdrop-blur-xl transition hover:border-electric-300/60 hover:bg-electric-500/15 sm:end-5 sm:start-auto"
      >
        <Palette className="h-4 w-4 text-electric-300" />
        Production Studio
      </Link>
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
      />
      <GlobalSearch
        isOpen={globalSearchOpen}
        onClose={() => setGlobalSearchOpen(false)}
      />
      <LanguageVoiceControls />
    </div>
  );
}
