"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";

import CommandPalette from "@/components/layout/CommandPalette";
import Sidebar from "@/components/layout/Sidebar";
import TopBar from "@/components/layout/TopBar";
import GlobalSearch from "@/components/search/GlobalSearch";

export default function DashboardShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [globalSearchOpen, setGlobalSearchOpen] = useState(false);

  const toggleSidebar = useCallback(() => {
    if (mobile) {
      setMobileSidebarOpen((current) => !current);
      return;
    }
    setSidebarCollapsed((current) => !current);
  }, [mobile]);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(max-width: 767px)");
    const synchronizeViewport = () => {
      setMobile(mediaQuery.matches);
      if (!mediaQuery.matches) setMobileSidebarOpen(false);
    };

    synchronizeViewport();
    mediaQuery.addEventListener("change", synchronizeViewport);
    return () => mediaQuery.removeEventListener("change", synchronizeViewport);
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (event.shiftKey) {
          setGlobalSearchOpen((current) => !current);
        } else {
          setCommandPaletteOpen((current) => !current);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="min-h-screen bg-space-950">
      {mobile && mobileSidebarOpen ? (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-[45] bg-black/60 backdrop-blur-sm"
          onClick={() => setMobileSidebarOpen(false)}
        />
      ) : null}
      <Sidebar
        collapsed={mobile ? false : sidebarCollapsed}
        mobile={mobile}
        mobileOpen={mobileSidebarOpen}
        onNavigate={() => setMobileSidebarOpen(false)}
        onToggle={toggleSidebar}
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
          marginLeft: mobile ? 0 : sidebarCollapsed ? 72 : 280,
          paddingTop: 64,
        }}
        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        className="min-h-screen p-4 sm:p-6"
      >
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3 }}
        >
          {children}
        </motion.div>
      </motion.main>
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
      />
      <GlobalSearch
        isOpen={globalSearchOpen}
        onClose={() => setGlobalSearchOpen(false)}
      />
    </div>
  );
}
